"""Unit tests for the Phase B drafting orchestrator.

All external services (BrainClient, Qdrant, Postgres, NAS reads) are mocked.
Live BRAIN dry-runs against the 49B model are operator-paced and not part
of this test surface — each synthesis call is 5-10 min wall-clock.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from backend.services.brain_client import BrainClient
from backend.services.case_briefing_compose import (
    COMPOSER_NAME,
    COMPOSER_VERSION,
    FYEO_WARNING,
    GROUNDING_MIN_CITATIONS,
    GroundingPacket,
    SECTION_MODE_MECHANICAL,
    SECTION_MODE_OPERATOR_WRITTEN,
    SECTION_MODE_SYNTHESIS,
    SectionResult,
    TEN_SECTIONS,
    stage_2_synthesize,
    stage_4_assemble,
)
from backend.services import case_briefing_synthesizers as syn


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _packet(
    *,
    contains_privileged: bool = False,
    privileged_chunks: list[str] | None = None,
    work_product_chunks: list[str] | None = None,
    related_matters: list[str] | None = None,
    curated_files: list[dict] | None = None,
    case_metadata: dict | None = None,
) -> GroundingPacket:
    return GroundingPacket(
        case_slug_input="7il-v-knight-ndga-ii",
        case_slug_canonical="7il-v-knight-ndga-ii",
        case_metadata=case_metadata or {
            "case_name": "7 IL Properties LLC v. Knight",
            "case_number": "2:26-CV-00113-RWS",
            "court": "NDGA Federal",
            "our_role": "defendant",
            "status": "active",
            "case_type": "civil",
            "critical_date": "2026-06-15",
            "petition_date": "2026-04-15",
            "judge": "Hon. Richard W. Story",
            "plan_admin": None,
            "opposing_counsel": "Buchalter LLP — Goldberg",
        },
        related_matters=related_matters or ["7il-v-knight-ndga-i"],
        vault_documents=[
            {"id": "doc-1", "file_name": "Complaint.pdf", "mime_type": "application/pdf",
             "processing_status": "complete", "chunk_count": 30, "file_size_bytes": 1234567,
             "created_at": None, "nfs_path": "/mnt/x/Complaint.pdf"},
        ],
        email_archive_hits=[],
        curated_nas_files=curated_files or [
            {"document_id": "doc-1", "file_name": "Complaint.pdf", "cluster": "filings", "relevance": 0.8},
            {"document_id": "doc-2", "file_name": "Exhibit_E.pdf", "cluster": "exhibits", "relevance": 0.7},
        ],
        privileged_chunk_ids=["pid-1"] if (contains_privileged or privileged_chunks) else [],
        privileged_chunk_texts=privileged_chunks or ([] if not contains_privileged else
            ["[PRIVILEGED · MHT Legal · counsel] [Knight-Underwood-2022-09.eml] privileged content"]),
        work_product_chunk_ids=["wp-1", "wp-2"],
        work_product_chunk_texts=work_product_chunks or [
            "[Complaint.pdf] Plaintiff alleges breach of warranty re 92 Fish Trap on 2025-06-02.",
            "[Exhibit_E.pdf] River Heights inspection report dated April 12, 2021.",
        ],
        contains_privileged=contains_privileged,
    )


# ── Mechanical synthesizers ───────────────────────────────────────────────────

def test_section_01_case_summary_table_format():
    packet = _packet()
    out = syn.synthesize_mechanical("section_01_case_summary", packet)
    assert "| Field | Detail |" in out
    assert "Case Number" in out
    assert "2:26-CV-00113-RWS" in out
    assert "7il-v-knight-ndga-i" in out  # related matter listed


def test_section_03_parties_and_counsel_uses_db_fields():
    packet = _packet()
    out = syn.synthesize_mechanical("section_03_parties_and_counsel", packet)
    assert "Plaintiff" in out
    assert "Buchalter LLP" in out
    assert "Our role" in out


def test_section_06_evidence_inventory_clusters_present():
    packet = _packet()
    out = syn.synthesize_mechanical("section_06_evidence_inventory", packet)
    assert "Curated Evidence Set" in out
    assert "filings" in out
    assert "exhibits" in out
    # Sovereign retrieval snapshot included
    assert "Work-product chunks retrieved" in out
    assert "legal_ediscovery" in out


def test_section_10_filing_checklist_includes_critical_date():
    packet = _packet()
    out = syn.synthesize_mechanical("section_10_filing_checklist", packet)
    assert "Critical date on file" in out
    assert "2026-06-15" in out


def test_unknown_mechanical_section_raises():
    packet = _packet()
    with pytest.raises(ValueError):
        syn.synthesize_mechanical("section_99_phantom", packet)


# ── Synthesis dispatch ────────────────────────────────────────────────────────

class _FakeIterator:
    """Async iterator that yields a fixed transcript so tests can exercise the
    synthesis path without spinning up BrainClient transports."""
    def __init__(self, chunks: list[str]):
        self._chunks = chunks
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        c = self._chunks[self._i]
        self._i += 1
        return c


class _FakeBrain:
    def __init__(self, transcript: str):
        self._transcript = transcript

    async def chat(self, **kwargs):  # signature-compatible with BrainClient.chat
        return _FakeIterator([self._transcript])


@pytest.mark.asyncio
async def test_stage_2_mechanical_section_passthrough():
    packet = _packet()
    fake = _FakeBrain("not-used")
    results = await stage_2_synthesize(packet, brain_client=fake)  # type: ignore[arg-type]
    assert "section_01_case_summary" in results
    s1 = results["section_01_case_summary"]
    assert s1.mode == SECTION_MODE_MECHANICAL
    assert "2:26-CV-00113-RWS" in s1.content
    s9 = results["section_09_recommended_strategy"]
    assert s9.mode == SECTION_MODE_OPERATOR_WRITTEN


@pytest.mark.asyncio
async def test_stage_2_synthesis_section_calls_brain_with_streaming():
    """The synthesizer must call BrainClient.chat with stream=True implicitly
    (default) — the body of the call is what we assert on."""
    packet = _packet(work_product_chunks=[
        "[Complaint.pdf] alleges X.",
        "[Exhibit_E.pdf] inspection report.",
        "[63-9_Exh._H_-_92_Fish_Trap_Package.pdf] PSA pages.",
    ])

    captured: dict[str, Any] = {}

    class _CaptureBrain:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            transcript = (
                "Timeline for 92 Fish Trap: see [Complaint.pdf] for breach allegations. "
                "[Exhibit_E.pdf] dated April 12, 2021. "
                "[63-9_Exh._H_-_92_Fish_Trap_Package.pdf] PSA — recorded 2025-06-02."
            )
            return _FakeIterator([transcript])

    results = await stage_2_synthesize(packet, brain_client=_CaptureBrain())  # type: ignore[arg-type]
    assert "section_02_critical_timeline" in results
    s2 = results["section_02_critical_timeline"]
    assert s2.mode == SECTION_MODE_SYNTHESIS
    assert s2.content
    assert captured.get("stream") is True
    assert captured.get("temperature") == 0.0
    # All 3 source bracketed names should be detected as grounded citations
    assert len(s2.grounding_citations) >= GROUNDING_MIN_CITATIONS
    assert s2.fail_reason is None


@pytest.mark.asyncio
async def test_stage_2_synthesis_fail_grounding_when_too_few_citations():
    packet = _packet(work_product_chunks=[
        "[only-one.pdf] minimal evidence chunk."
    ])

    class _UngroundedBrain:
        async def chat(self, **kwargs):
            # Response cites the one source — only 1 grounded citation possible.
            transcript = "Per [only-one.pdf], the case is ongoing."
            return _FakeIterator([transcript])

    results = await stage_2_synthesize(packet, brain_client=_UngroundedBrain())  # type: ignore[arg-type]
    s4 = results["section_04_claims_analysis"]
    assert s4.fail_reason is not None
    assert "FAIL_GROUNDING" in s4.fail_reason


@pytest.mark.asyncio
async def test_stage_2_section_07_excludes_defense_counsel():
    """Section 07's privilege filter must drop chunks whose header references
    operator-defense-counsel domains/names BEFORE BRAIN sees them."""
    packet = _packet(work_product_chunks=[
        "[Goldberg-Buchalter-2026-04.eml] adversary counsel demand letter.",
        "[Knight-Podesta-2023-05.eml] privileged defense-counsel email body — must be filtered.",
        "[Knight-Sanker-2024-03.eml] privileged defense-counsel email — must be filtered.",
        "[2025.02.01-Re-Wilson-Knight-Complaint.eml] operator-outbound to closing attorney.",
    ])

    captured: dict[str, Any] = {}

    class _PrivilegeAwareBrain:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            content = kwargs["messages"][-1]["content"]
            captured["user_prompt"] = content
            return _FakeIterator(["[Goldberg-Buchalter-2026-04.eml] adversary present. [2025.02.01-Re-Wilson-Knight-Complaint.eml] operator outbound."])

    section_07_only = (
        ("section_07_email_intelligence_report", "7. Email Intelligence Report", SECTION_MODE_SYNTHESIS),
    )
    results = await stage_2_synthesize(
        packet, sections=section_07_only, brain_client=_PrivilegeAwareBrain(),  # type: ignore[arg-type]
    )
    user_prompt = captured["user_prompt"]
    # Defense-counsel chunks must have been filtered out before the prompt
    assert "Knight-Podesta-2023-05.eml" not in user_prompt
    assert "Knight-Sanker-2024-03.eml" not in user_prompt
    # Adversary + third-party chunks survive
    assert "Goldberg-Buchalter-2026-04.eml" in user_prompt
    assert "2025.02.01-Re-Wilson-Knight-Complaint.eml" in user_prompt
    # Section 7 result must NOT carry contains_privileged (privileged were stripped)
    assert results["section_07_email_intelligence_report"].contains_privileged is False


# ── Stage 4 assembly ──────────────────────────────────────────────────────────

def test_stage_4_assembly_appends_fyeo_when_privileged(tmp_path: Path):
    packet = _packet(contains_privileged=True)
    sections = {
        "section_01_case_summary": SectionResult(
            section_id="section_01_case_summary",
            title="1. Case Summary",
            mode=SECTION_MODE_MECHANICAL,
            content="| Field | Detail |\n|---|---|\n| Case Number | 2:26-CV-00113-RWS |",
        ),
    }
    out = stage_4_assemble(packet, sections, output_dir=tmp_path)
    body = out.read_text(encoding="utf-8")
    assert FYEO_WARNING in body
    assert "Case Number" in body
    assert COMPOSER_NAME in body
    assert COMPOSER_VERSION in body


def test_stage_4_assembly_omits_fyeo_when_not_privileged(tmp_path: Path):
    packet = _packet(contains_privileged=False)
    sections = {
        "section_01_case_summary": SectionResult(
            section_id="section_01_case_summary",
            title="1. Case Summary",
            mode=SECTION_MODE_MECHANICAL,
            content="ok",
        ),
    }
    out = stage_4_assemble(packet, sections, output_dir=tmp_path)
    body = out.read_text(encoding="utf-8")
    assert FYEO_WARNING not in body


def test_stage_4_version_increment(tmp_path: Path):
    packet = _packet()
    sections = {
        "section_01_case_summary": SectionResult(
            section_id="section_01_case_summary",
            title="1. Case Summary",
            mode=SECTION_MODE_MECHANICAL,
            content="x",
        ),
    }
    out1 = stage_4_assemble(packet, sections, output_dir=tmp_path, case_name_safe="Acme")
    assert "_v1_" in out1.name
    out2 = stage_4_assemble(packet, sections, output_dir=tmp_path, case_name_safe="Acme")
    assert "_v2_" in out2.name
    out3 = stage_4_assemble(packet, sections, output_dir=tmp_path, case_name_safe="Acme")
    assert "_v3_" in out3.name


def test_stage_4_explicit_version_wins(tmp_path: Path):
    packet = _packet()
    sections = {
        "section_01_case_summary": SectionResult(
            section_id="section_01_case_summary",
            title="1. Case Summary",
            mode=SECTION_MODE_MECHANICAL,
            content="x",
        ),
    }
    out = stage_4_assemble(
        packet, sections, output_dir=tmp_path, version=42, case_name_safe="Acme"
    )
    assert "_v42_" in out.name


def test_section_section_07_chunk_classifier_detects_defense_counsel():
    """Direct unit test for the privilege filter helper."""
    assert syn._is_defense_counsel_chunk(
        "[Knight-Podesta-2023-05.eml] privileged"
    ) is True
    assert syn._is_defense_counsel_chunk(
        "[fpodesta@fgplaw.com] inbound"
    ) is True
    assert syn._is_defense_counsel_chunk(
        "[Goldberg-Buchalter-2026-04.eml] adversary, not defense"
    ) is False
    assert syn._is_defense_counsel_chunk(
        "[2025.02.01-Re-Wilson-Knight-Complaint.eml] operator outbound"
    ) is False


def test_ten_sections_modes_locked():
    """Pin the section ↔ mode mapping so a regression that flips a mechanical
    section to synthesis (or vice versa) breaks loudly here, not silently in
    production."""
    expected_modes = {
        "section_01_case_summary": SECTION_MODE_MECHANICAL,
        "section_02_critical_timeline": SECTION_MODE_SYNTHESIS,
        "section_03_parties_and_counsel": SECTION_MODE_MECHANICAL,
        "section_04_claims_analysis": SECTION_MODE_SYNTHESIS,
        "section_05_key_defenses_identified": SECTION_MODE_SYNTHESIS,
        "section_06_evidence_inventory": SECTION_MODE_MECHANICAL,
        "section_07_email_intelligence_report": SECTION_MODE_SYNTHESIS,
        "section_08_financial_exposure_analysis": SECTION_MODE_SYNTHESIS,
        "section_09_recommended_strategy": SECTION_MODE_OPERATOR_WRITTEN,
        "section_10_filing_checklist": SECTION_MODE_MECHANICAL,
    }
    actual_modes = {sid: mode for sid, _, mode in TEN_SECTIONS}
    assert actual_modes == expected_modes
