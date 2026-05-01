"""Phase B drafting orchestrator.

Produces 10-section attorney briefing packages from a curated evidence set
plus sovereign BRAIN inference. Stage 0 (curate) and Stage 4 (assemble) are
deterministic; Stages 1-3 (grounding + synthesis + operator review) bracket
the LLM-grounded work.

Read-only consumer of `legal.cases`, `legal.vault_documents`, and the
Qdrant retrieval primitives in `legal_council`. No writes to any sovereign
store from this module — outputs land on NAS at the canonical filings path,
or `/tmp` for dry-runs.

This is v0.1: orchestrator skeleton + dataclasses + Stage 0/1/4
implementations + section dispatcher. The synthesis sections (02/04/05/07/08)
have synthesizer functions that call BrainClient via the streaming-default
path; live execution against the 49B model is operator-paced and not part of
this PR's automated test surface (each synthesis call is 5-10 min wall-clock
on the 49B Nemotron at ~3.7 tok/s). Unit tests mock BrainClient + Qdrant.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Sequence, cast

import httpx
from sqlalchemy import text as sa_text

from backend.api.legal_cases import _resolve_case_slug
from backend.services.brain_client import BrainClient, BrainClientError
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_council import (
    freeze_context,
    freeze_privileged_context,
)


COMPOSER_NAME = "case_briefing_compose"
COMPOSER_VERSION = "v0.1"

logger = logging.getLogger(COMPOSER_NAME)


SECTION_MODE_MECHANICAL = "mechanical"
SECTION_MODE_SYNTHESIS = "synthesis"
SECTION_MODE_OPERATOR_WRITTEN = "operator_written"


TEN_SECTIONS: list[tuple[str, str, str]] = [
    ("section_01_case_summary", "1. Case Summary", SECTION_MODE_MECHANICAL),
    ("section_02_critical_timeline", "2. Critical Timeline", SECTION_MODE_SYNTHESIS),
    ("section_03_parties_and_counsel", "3. Parties & Counsel", SECTION_MODE_MECHANICAL),
    ("section_04_claims_analysis", "4. Claims Analysis", SECTION_MODE_SYNTHESIS),
    ("section_05_key_defenses_identified", "5. Key Defenses Identified", SECTION_MODE_SYNTHESIS),
    ("section_06_evidence_inventory", "6. Evidence Inventory", SECTION_MODE_MECHANICAL),
    ("section_07_email_intelligence_report", "7. Email Intelligence Report", SECTION_MODE_SYNTHESIS),
    ("section_08_financial_exposure_analysis", "8. Financial Exposure Analysis", SECTION_MODE_SYNTHESIS),
    ("section_09_recommended_strategy", "9. Recommended Strategy", SECTION_MODE_OPERATOR_WRITTEN),
    ("section_10_filing_checklist", "10. Filing Checklist", SECTION_MODE_MECHANICAL),
]

GROUNDING_MIN_CITATIONS = 3
FYEO_WARNING = (
    "**FOR YOUR EYES ONLY (FYEO).** This briefing package contains attorney "
    "work product and references to privileged communications retrieved from "
    "the sovereign Fortress vault. Do not distribute beyond engaged counsel "
    "without operator authorization."
)


@dataclass
class CuratedItem:
    document_id: str
    file_name: str
    nfs_path: str
    mime_type: str
    cluster: str
    relevance: float
    chunk_count: int


@dataclass
class CuratedSet:
    case_slug: str
    items: list[CuratedItem] = field(default_factory=list)
    deduped_against_email_archive: int = 0


@dataclass
class GroundingPacket:
    case_slug_input: str
    case_slug_canonical: str
    case_metadata: dict
    related_matters: list[str]
    vault_documents: list[dict]
    email_archive_hits: list[dict]
    curated_nas_files: list[dict]
    privileged_chunk_ids: list[str]
    privileged_chunk_texts: list[str]
    work_product_chunk_ids: list[str]
    work_product_chunk_texts: list[str]
    contains_privileged: bool


@dataclass
class SectionResult:
    section_id: str
    title: str
    mode: str
    content: str
    grounding_citations: list[str] = field(default_factory=list)
    retrieval_chunk_ids: list[str] = field(default_factory=list)
    contains_privileged: bool = False
    operator_status: str = "draft"
    fail_reason: Optional[str] = None


# ── Stage 0 — Curate ──────────────────────────────────────────────────────────

async def stage_0_curate(case_slug: str) -> CuratedSet:
    """Cluster `legal.vault_documents` by mime_type. Read-only; no writes.

    v0.1: deterministic mime-type clustering. Future revisions can layer on
    keyword classification + relevance scoring (the brief's full §5.2). For
    now, every vault document gets a default relevance score derived from
    chunk_count (well-chunked documents are more likely substantive).
    """
    items: list[CuratedItem] = []
    async with LegacySession() as session:
        rows = await session.execute(
            sa_text(
                """
                SELECT id::text AS id, file_name, nfs_path, mime_type, chunk_count
                FROM legal.vault_documents
                WHERE case_slug = :s AND processing_status IN ('complete', 'completed')
                ORDER BY created_at DESC
                """
            ),
            {"s": case_slug},
        )
        for r in rows.fetchall():
            chunk_count = r.chunk_count or 0
            relevance = min(1.0, chunk_count / 50.0)
            cluster = _classify_cluster(r.mime_type, r.file_name)
            items.append(
                CuratedItem(
                    document_id=r.id,
                    file_name=r.file_name,
                    nfs_path=r.nfs_path,
                    mime_type=r.mime_type,
                    cluster=cluster,
                    relevance=relevance,
                    chunk_count=chunk_count,
                )
            )
    items.sort(key=lambda it: (-it.relevance, it.file_name))
    logger.info(
        "stage_0_curate_complete  case=%s  items=%d  clusters=%s",
        case_slug, len(items), sorted({i.cluster for i in items}),
    )
    return CuratedSet(case_slug=case_slug, items=items)


def _classify_cluster(mime_type: str, file_name: str) -> str:
    name = (file_name or "").lower()
    if "deposition" in name or "depo" in name:
        return "depositions"
    if "exhibit" in name or "exh" in name:
        return "exhibits"
    if "complaint" in name or "answer" in name or "motion" in name or "msj" in name or "loa" in name:
        return "filings"
    if "psa" in name or "deed" in name or "easement" in name or "warranty" in name:
        return "contracts"
    if "inspection" in name or "survey" in name:
        return "inspections"
    if mime_type == "message/rfc822" or name.endswith(".eml"):
        return "correspondence"
    return "other"


# ── Stage 1 — Grounding packet ────────────────────────────────────────────────

async def stage_1_grounding_packet(
    case_slug_input: str,
    curated: CuratedSet,
    *,
    top_k: int = 15,
    privileged_top_k: int = 10,
    grounding_query: Optional[str] = None,
) -> GroundingPacket:
    """Pull case metadata, retrieval chunks, and curated set into a structured
    packet ready for synthesis.

    Reuses `freeze_context` and `freeze_privileged_context` from
    `legal_council` — no retrieval-primitive changes.
    """
    async with LegacySession() as session:
        canonical = await _resolve_case_slug(session, case_slug_input)
        case_row = await session.execute(
            sa_text("SELECT * FROM legal.cases WHERE case_slug = :s"),
            {"s": canonical},
        )
        case_metadata_row = case_row.fetchone()
        case_metadata: dict[str, Any] = (
            dict(case_metadata_row._mapping) if case_metadata_row is not None else {}
        )

        # related_matters: stored as JSONB on legal.cases per §3.1 of the
        # caselaw audit and the legal_council._resolve_related_matters_slugs
        # helper.
        related: list[str] = []
        rm_row = await session.execute(
            sa_text("SELECT related_matters FROM legal.cases WHERE case_slug = :s"),
            {"s": canonical},
        )
        rm_value = rm_row.fetchone()
        raw_related = rm_value[0] if rm_value is not None else None
        if isinstance(raw_related, list):
            related = [s for s in raw_related if isinstance(s, str) and s and s != canonical]
        elif isinstance(raw_related, str):
            try:
                parsed = json.loads(raw_related)
                if isinstance(parsed, list):
                    related = [s for s in parsed if isinstance(s, str) and s and s != canonical]
            except (TypeError, ValueError):
                related = []

        vault_rows = await session.execute(
            sa_text(
                """
                SELECT id::text AS id, file_name, mime_type, processing_status,
                       chunk_count, file_size_bytes, created_at, nfs_path
                FROM legal.vault_documents
                WHERE case_slug = :s
                ORDER BY created_at DESC
                """
            ),
            {"s": canonical},
        )
        vault_documents = [dict(row._mapping) for row in vault_rows.fetchall()]

        email_hits: list[dict] = []
        try:
            email_rows = await session.execute(
                sa_text(
                    """
                    SELECT id, sent_at, sender, subject
                    FROM public.email_archive
                    WHERE division = 'HEDGE_FUND'
                    LIMIT 0
                    """
                ),
            )
            # Real email_archive query patterns (Captain / Section-7 inputs)
            # live in dedicated CSV exports under
            # docs/case-briefing/email-archive-query-*.csv. v0.1 reuses the
            # exported CSVs as the email-archive surface; ingestion of fresh
            # query results is a future enhancement.
            _ = email_rows.fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.info("email_archive_query_skipped  reason=%s", str(exc)[:120])

    case_brief_for_retrieval = (
        grounding_query
        or _build_default_grounding_query(case_metadata)
        or canonical
    )

    wp_ids, wp_chunks = await freeze_context(
        case_brief=case_brief_for_retrieval, top_k=top_k, case_slug=canonical
    )
    for rel_slug in related:
        ids, chunks = await freeze_context(
            case_brief=case_brief_for_retrieval, top_k=top_k, case_slug=rel_slug
        )
        wp_ids.extend(ids)
        wp_chunks.extend(chunks)

    priv_ids, priv_chunks = await freeze_privileged_context(
        case_brief=case_brief_for_retrieval, top_k=privileged_top_k, case_slug=canonical
    )

    contains_privileged = bool(priv_chunks)
    logger.info(
        "stage_1_grounding_packet_complete  case=%s  vault=%d  wp_chunks=%d  priv_chunks=%d",
        canonical, len(vault_documents), len(wp_chunks), len(priv_chunks),
    )
    return GroundingPacket(
        case_slug_input=case_slug_input,
        case_slug_canonical=canonical,
        case_metadata=case_metadata,
        related_matters=related,
        vault_documents=vault_documents,
        email_archive_hits=email_hits,
        curated_nas_files=[
            {
                "document_id": it.document_id,
                "file_name": it.file_name,
                "cluster": it.cluster,
                "relevance": it.relevance,
            }
            for it in curated.items
        ],
        privileged_chunk_ids=priv_ids,
        privileged_chunk_texts=priv_chunks,
        work_product_chunk_ids=wp_ids,
        work_product_chunk_texts=wp_chunks,
        contains_privileged=contains_privileged,
    )


def _build_default_grounding_query(case_metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("case_name", "case_number", "court", "our_role", "our_claim_basis"):
        v = case_metadata.get(key)
        if isinstance(v, str) and v:
            parts.append(v)
    return " ".join(parts)


# ── Stage 2 — Synthesize ──────────────────────────────────────────────────────

async def stage_2_synthesize(
    packet: GroundingPacket,
    *,
    sections: Sequence[tuple[str, str, str]] = tuple(TEN_SECTIONS),
    brain_client: Optional[BrainClient] = None,
) -> dict[str, SectionResult]:
    """Per-section dispatch. Mechanical sections deterministic. Synthesis
    sections call BRAIN with the streaming-default discipline.
    """
    from backend.services import case_briefing_synthesizers as syn

    results: dict[str, SectionResult] = {}
    client = brain_client or BrainClient()

    for section_id, title, mode in sections:
        if mode == SECTION_MODE_MECHANICAL:
            content = syn.synthesize_mechanical(section_id, packet)
            results[section_id] = SectionResult(
                section_id=section_id,
                title=title,
                mode=mode,
                content=content,
                contains_privileged=False,
            )
        elif mode == SECTION_MODE_OPERATOR_WRITTEN:
            results[section_id] = SectionResult(
                section_id=section_id,
                title=title,
                mode=mode,
                content=syn.operator_written_placeholder(title),
                contains_privileged=False,
            )
        elif mode == SECTION_MODE_SYNTHESIS:
            try:
                # thinking_token_budget removed Wave 4 — vLLM mainline requires
                # --reasoning-config on the frontier (not currently set). NIM's
                # reasoning_budget is a separate path. Re-engagement requires
                # frontier redeploy; keep BrainClient kwarg for that path.
                # See docs/research/nemotron-3-super-deep-research-2026-04-30.md §2.
                policy = syn.SECTION_REASONING_POLICY.get(section_id, {})
                policy_kwargs = {
                    k: v for k, v in policy.items() if v is not None
                }
                result = await syn.synthesize_synthesis_section(
                    section_id,
                    packet,
                    brain_client=client,
                    **policy_kwargs,
                )
                if len(result.grounding_citations) < GROUNDING_MIN_CITATIONS:
                    result.fail_reason = (
                        f"FAIL_GROUNDING: only {len(result.grounding_citations)} grounded "
                        f"citations; minimum required is {GROUNDING_MIN_CITATIONS}"
                    )
                results[section_id] = result
            except BrainClientError as exc:
                results[section_id] = SectionResult(
                    section_id=section_id,
                    title=title,
                    mode=mode,
                    content="",
                    fail_reason=f"BRAIN_ERROR: {exc}",
                )
        else:
            raise ValueError(f"Unknown section mode {mode!r} for {section_id}")
    return results


# ── Stage 4 — Assemble final ──────────────────────────────────────────────────

def stage_4_assemble(
    packet: GroundingPacket,
    sections: dict[str, SectionResult],
    *,
    output_dir: Path,
    case_name_safe: Optional[str] = None,
    version: Optional[int] = None,
    composer_metadata: Optional[dict[str, Any]] = None,
) -> Path:
    """Compose the markdown package + write to `output_dir`.

    Filename pattern: `Attorney_Briefing_Package_<CASE_NAME>_v<N>_<YYYYMMDD>.md`.
    The version increments based on existing files in `output_dir` if not
    explicitly provided.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if case_name_safe is None:
        raw_name = str(packet.case_metadata.get("case_name") or packet.case_slug_canonical)
        case_name_safe = re.sub(r"[^A-Za-z0-9]+", "_", raw_name).strip("_") or packet.case_slug_canonical

    if version is None:
        version = _next_version(output_dir, case_name_safe)

    today = date.today().strftime("%Y%m%d")
    filename = f"Attorney_Briefing_Package_{case_name_safe}_v{version}_{today}.md"
    out_path = output_dir / filename

    contains_privileged_anywhere = packet.contains_privileged or any(
        s.contains_privileged for s in sections.values()
    )

    md_lines: list[str] = []
    md_lines.append(f"# Attorney Briefing Package — {packet.case_metadata.get('case_name') or packet.case_slug_canonical}")
    md_lines.append("")
    md_lines.append(f"**Case slug (canonical):** `{packet.case_slug_canonical}`")
    md_lines.append(f"**Case slug (input):** `{packet.case_slug_input}`")
    md_lines.append(f"**Composer:** {COMPOSER_NAME} {COMPOSER_VERSION}")
    md_lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    md_lines.append(f"**Output version:** v{version}")
    if composer_metadata:
        for k, v in composer_metadata.items():
            md_lines.append(f"**{k}:** {v}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    for section_id, _title, _mode in TEN_SECTIONS:
        result = sections.get(section_id)
        if result is None:
            continue
        md_lines.append(f"## {result.title}")
        md_lines.append("")
        md_lines.append(f"_Mode: `{result.mode}` · operator status: `{result.operator_status}`_")
        if result.fail_reason:
            md_lines.append(f"> ⚠️ **{result.fail_reason}**")
        if result.grounding_citations:
            md_lines.append(f"_Grounding citations: {len(result.grounding_citations)}_")
        if result.contains_privileged:
            md_lines.append("_Contains privileged content (FYEO)._")
        md_lines.append("")
        md_lines.append(result.content or "_(empty)_")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    if contains_privileged_anywhere:
        md_lines.append("")
        md_lines.append(FYEO_WARNING)
        md_lines.append("")

    out_path.write_text("\n".join(md_lines), encoding="utf-8")
    logger.info(
        "stage_4_assemble_complete  case=%s  out=%s  privileged=%s",
        packet.case_slug_canonical, str(out_path), contains_privileged_anywhere,
    )
    return out_path


def _next_version(output_dir: Path, case_name_safe: str) -> int:
    pattern = re.compile(
        rf"^Attorney_Briefing_Package_{re.escape(case_name_safe)}_v(\d+)_\d{{8}}\.md$"
    )
    versions: list[int] = []
    for p in output_dir.iterdir():
        m = pattern.match(p.name)
        if m:
            try:
                versions.append(int(m.group(1)))
            except ValueError:
                continue
    return (max(versions) + 1) if versions else 1


# ── Convenience: full-pipeline facade (for non-interactive callers) ──────────

async def compose(
    case_slug_input: str,
    *,
    output_dir: Path,
    grounding_query: Optional[str] = None,
    top_k: int = 15,
    privileged_top_k: int = 10,
    sections: Sequence[tuple[str, str, str]] = tuple(TEN_SECTIONS),
    brain_client: Optional[BrainClient] = None,
) -> tuple[GroundingPacket, dict[str, SectionResult], Path]:
    curated = await stage_0_curate(case_slug_input)
    packet = await stage_1_grounding_packet(
        case_slug_input,
        curated,
        top_k=top_k,
        privileged_top_k=privileged_top_k,
        grounding_query=grounding_query,
    )
    section_results = await stage_2_synthesize(
        packet, sections=sections, brain_client=brain_client
    )
    out_path = stage_4_assemble(packet, section_results, output_dir=output_dir)
    return packet, section_results, out_path
