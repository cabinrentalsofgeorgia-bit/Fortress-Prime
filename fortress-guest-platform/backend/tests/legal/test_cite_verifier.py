"""
Unit tests for backend.services.legal.cite_verifier.

All external calls (CourtListener, Ollama) are mocked.
No live HTTP requests are made.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.legal.cite_verifier import (  # type: ignore[import-not-found]
    CitationRecord,
    CitationType,
    DraftVerificationReport,
    VerificationStatus,
    _apply_corrections,
    _extract_regex,
    accept_draft,
    extract_citations,
    verify_citation,
    verify_draft,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_DRAFT = """
This Court has jurisdiction pursuant to 28 U.S.C. §§ 157 and 1334.
This is a core proceeding pursuant to 28 U.S.C. § 157(b)(2).
Under Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership,
507 U.S. 380 (1993), excusable neglect requires consideration of four factors.
See also Fed. R. Bankr. P. 3003(c)(3).
"""

DRAFT_WITH_NO_CITES = "This is a plain paragraph with no legal citations whatsoever."

DRAFT_WITH_BAD_CITE = """
This motion is supported by 28 U.S.C. § 157.
The non-existent case Totally Fake Co. v. Made Up Corp., 999 F.3d 1 (2099) is cited here.
"""

DRAFT_WITH_OCGA = """
Under O.C.G.A. § 44-7-30, landlord duties apply.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cl_response(case_name: str, snippet: str = "relevant snippet") -> dict:
    return {
        "results": [
            {
                "caseName": case_name,
                "snippet": snippet,
                "absolute_url": "/opinion/123456/",
                "url": "https://www.courtlistener.com/opinion/123456/",
            }
        ]
    }


def _make_cl_empty_response() -> dict:
    return {"results": []}


def _make_llm_response(content: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# Extraction tests — regex
# ---------------------------------------------------------------------------

def test_extract_federal_statute_regex() -> None:
    text = "This Court has jurisdiction pursuant to 28 U.S.C. § 157 and 1334."
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("U.S.C" in r for r in raws), f"Expected USC citation, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.FEDERAL_STATUTE.value in types


def test_extract_federal_case_regex() -> None:
    text = (
        "See Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership, "
        "507 U.S. 380 (1993)."
    )
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("Pioneer" in r or "507 U.S." in r for r in raws), f"Expected federal case, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.FEDERAL_CASE.value in types


def test_extract_federal_regulation_regex() -> None:
    text = "Pursuant to 12 C.F.R. § 226.2, the following applies."
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("C.F.R" in r for r in raws), f"Expected CFR citation, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.FEDERAL_REGULATION.value in types


def test_extract_federal_rule_regex() -> None:
    text = "Under Fed. R. Bankr. P. 3003(c)(3), the claim must be filed."
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("Bankr" in r or "3003" in r for r in raws), f"Expected Bankr rule, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.FEDERAL_RULE.value in types


def test_extract_state_statute_regex() -> None:
    text = "Under O.C.G.A. § 44-7-30, landlord duties apply."
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("O.C.G.A" in r for r in raws), f"Expected OCGA statute, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.STATE_STATUTE.value in types


def test_extract_state_case_regex() -> None:
    text = "As held in Smith v. Jones, 123 Ga. App. 456 (2001)."
    results = _extract_regex(text)
    raws = [r["raw"] for r in results]
    assert any("Ga." in r for r in raws), f"Expected GA state case, got: {raws}"
    types = [r["citation_type"] for r in results]
    assert CitationType.STATE_CASE.value in types


@pytest.mark.asyncio
async def test_extract_llm_supplement() -> None:
    """LLM finds a cite that regex missed."""
    text = "As discussed in the Supremacy Clause doctrine (see Article VI)."
    # Regex will find nothing; LLM supplement adds a cite
    llm_payload = json.dumps([
        {
            "raw": "Article VI of the U.S. Constitution",
            "type": "federal_statute",
            "proposition": "As discussed in the Supremacy Clause doctrine.",
        }
    ])
    with patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response(llm_payload),
    ):
        results = await extract_citations(text, use_llm=True)

    raws = [r["raw"] for r in results]
    assert any("Article VI" in r for r in raws), f"LLM cite not found in: {raws}"


# ---------------------------------------------------------------------------
# Verification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_federal_case_found() -> None:
    """CourtListener returns a matching case → VERIFIED."""
    record = {
        "raw": "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership, 507 U.S. 380 (1993)",
        "citation_type": CitationType.FEDERAL_CASE.value,
        "proposition": "Excusable neglect requires four factors.",
    }
    cl_response = _make_cl_response(
        "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership",
        snippet="The Court held that excusable neglect requires four factors.",
    )
    sem = asyncio.Semaphore(3)
    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=cl_response,
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("SUPPORTS\nThe snippet supports the proposition."),
    ):
        result = await verify_citation(record, sem, use_llm_support=True)

    assert result.level1_status == VerificationStatus.VERIFIED
    assert result.level2_text is not None
    assert result.final_status in (VerificationStatus.VERIFIED, VerificationStatus.UNCHECKABLE)


@pytest.mark.asyncio
async def test_verify_federal_case_not_found() -> None:
    """CourtListener returns no results → NOT_FOUND."""
    record = {
        "raw": "Totally Fake Co. v. Made Up Corp., 999 F.3d 1 (2099)",
        "citation_type": CitationType.FEDERAL_CASE.value,
        "proposition": "This cite proves nothing.",
    }
    sem = asyncio.Semaphore(3)
    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=_make_cl_empty_response(),
    ):
        result = await verify_citation(record, sem)

    assert result.level1_status == VerificationStatus.NOT_FOUND
    assert result.final_status == VerificationStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_verify_federal_rule_valid_range() -> None:
    """Fed. R. Bankr. P. 3003 → VERIFIED (in range 1001-9036)."""
    record = {
        "raw": "Fed. R. Bankr. P. 3003(c)(3)",
        "citation_type": CitationType.FEDERAL_RULE.value,
        "proposition": "The claim must be filed timely.",
    }
    sem = asyncio.Semaphore(3)
    result = await verify_citation(record, sem)
    assert result.level1_status == VerificationStatus.VERIFIED
    assert result.final_status in (VerificationStatus.VERIFIED, VerificationStatus.UNCHECKABLE)


@pytest.mark.asyncio
async def test_verify_federal_rule_invalid_range() -> None:
    """Fed. R. Bankr. P. 9999 → NOT_FOUND (above 9036)."""
    record = {
        "raw": "Fed. R. Bankr. P. 9999",
        "citation_type": CitationType.FEDERAL_RULE.value,
        "proposition": "Some rule.",
    }
    sem = asyncio.Semaphore(3)
    result = await verify_citation(record, sem)
    assert result.level1_status == VerificationStatus.NOT_FOUND
    assert result.final_status == VerificationStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_verify_federal_statute_valid_title() -> None:
    """28 U.S.C. § 157 → UNCHECKABLE (valid title, no full-text lookup)."""
    record = {
        "raw": "28 U.S.C. § 157",
        "citation_type": CitationType.FEDERAL_STATUTE.value,
        "proposition": "This court has jurisdiction.",
    }
    sem = asyncio.Semaphore(3)
    result = await verify_citation(record, sem)
    # Valid title → UNCHECKABLE (not NOT_FOUND)
    assert result.level1_status == VerificationStatus.UNCHECKABLE
    assert result.final_status == VerificationStatus.UNCHECKABLE


@pytest.mark.asyncio
async def test_verify_federal_statute_invalid_title() -> None:
    """99 U.S.C. § 1 → NOT_FOUND (title 99 doesn't exist)."""
    record = {
        "raw": "99 U.S.C. § 1",
        "citation_type": CitationType.FEDERAL_STATUTE.value,
        "proposition": "Some nonexistent provision.",
    }
    sem = asyncio.Semaphore(3)
    result = await verify_citation(record, sem)
    assert result.level1_status == VerificationStatus.NOT_FOUND
    assert result.final_status == VerificationStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_verify_level3_support_pass() -> None:
    """Source text supports proposition → VERIFIED at level3."""
    record = {
        "raw": "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership, 507 U.S. 380 (1993)",
        "citation_type": CitationType.FEDERAL_CASE.value,
        "proposition": "Excusable neglect has four factors.",
    }
    cl_response = _make_cl_response(
        "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership",
        snippet="Court considered four factors for excusable neglect.",
    )
    sem = asyncio.Semaphore(3)
    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=cl_response,
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("SUPPORTS\nThe snippet directly addresses the four-factor test."),
    ):
        result = await verify_citation(record, sem, use_llm_support=True)

    assert result.level3_status == VerificationStatus.VERIFIED
    assert result.final_status == VerificationStatus.VERIFIED


@pytest.mark.asyncio
async def test_verify_level3_support_fail() -> None:
    """Source text contradicts proposition → MISQUOTED at level3."""
    record = {
        "raw": "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership, 507 U.S. 380 (1993)",
        "citation_type": CitationType.FEDERAL_CASE.value,
        "proposition": "The court held that no factors apply to excusable neglect.",
    }
    cl_response = _make_cl_response(
        "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership",
        snippet="The court held that four factors must be weighed for excusable neglect.",
    )
    sem = asyncio.Semaphore(3)
    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=cl_response,
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("DOES_NOT_SUPPORT\nThe snippet contradicts the proposition."),
    ):
        result = await verify_citation(record, sem, use_llm_support=True)

    assert result.level3_status == VerificationStatus.MISQUOTED
    assert result.final_status == VerificationStatus.MISQUOTED


@pytest.mark.asyncio
async def test_verify_level3_uncheckable_skipped() -> None:
    """No level2_text → level3 UNCHECKABLE."""
    record = {
        "raw": "28 U.S.C. § 157",
        "citation_type": CitationType.FEDERAL_STATUTE.value,
        "proposition": "Jurisdiction.",
    }
    sem = asyncio.Semaphore(3)
    result = await verify_citation(record, sem)
    # No text retrieval for statutes
    assert result.level2_text is None
    assert result.level3_status == VerificationStatus.UNCHECKABLE


# ---------------------------------------------------------------------------
# accept_draft tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accept_draft_all_verified() -> None:
    """All cites valid → passes=True, clean draft."""
    draft = "See 28 U.S.C. § 157. Also Fed. R. Bankr. P. 3003."

    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=_make_cl_response("Pioneer Inv. Co. v. Brunswick"),
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("[]"),
    ), patch(
        "backend.services.legal.cite_verifier.httpx.AsyncClient",
    ) as mock_httpx:
        # Mock the reachability check in accept_draft
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx.return_value)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value.get = AsyncMock(return_value=mock_resp)

        passes, _, corrected = await accept_draft(draft)

    # 28 USC § 157 → UNCHECKABLE, Fed R Bankr P 3003 → VERIFIED
    # No NOT_FOUND → passed_gate should be True
    assert passes is True
    assert "[CITATION FAILED VERIFICATION" not in corrected


@pytest.mark.asyncio
async def test_accept_draft_not_found_strips_cite() -> None:
    """NOT_FOUND cite → stripped from corrected_draft with marker."""
    draft = (
        "See Totally Fake Co. v. Made Up Corp., 999 F.3d 1 (2099). "
        "This cite does not exist."
    )

    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=_make_cl_empty_response(),
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("[]"),
    ), patch(
        "backend.services.legal.cite_verifier.httpx.AsyncClient",
    ) as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx.return_value)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value.get = AsyncMock(return_value=mock_resp)

        passes, _, corrected = await accept_draft(draft)

    assert "[CITATION FAILED VERIFICATION — NOT FOUND]" in corrected
    assert passes is False


@pytest.mark.asyncio
async def test_accept_draft_misquoted_flags_cite() -> None:
    """MISQUOTED → flagged but kept in corrected_draft."""
    draft = (
        "Under Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership, "
        "507 U.S. 380 (1993), the court held that no factors apply."
    )
    cl_response = _make_cl_response(
        "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership",
        snippet="The court weighed four factors for excusable neglect.",
    )

    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=cl_response,
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("DOES_NOT_SUPPORT\nContradicts the proposition."),
    ), patch(
        "backend.services.legal.cite_verifier.httpx.AsyncClient",
    ) as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx.return_value)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value.get = AsyncMock(return_value=mock_resp)

        _, _, corrected = await accept_draft(draft)

    # MISQUOTED — flagged but not stripped
    assert "[CITE MAY NOT SUPPORT PROPOSITION — VERIFY]" in corrected
    # pioneer still in draft
    assert "Pioneer" in corrected


@pytest.mark.asyncio
async def test_accept_draft_courtlistener_down_raises() -> None:
    """Connection error → RuntimeError."""
    import httpx as httpx_module

    with patch(
        "backend.services.legal.cite_verifier.httpx.AsyncClient",
    ) as mock_httpx:
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx.return_value)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value.get = AsyncMock(
            side_effect=httpx_module.ConnectError("Connection refused")
        )

        with pytest.raises(RuntimeError, match="CourtListener unreachable"):
            await accept_draft("Some draft with 28 U.S.C. § 157.")


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline_with_real_citation_text() -> None:
    """End-to-end with mocked CL response and SAMPLE_DRAFT."""
    cl_response = _make_cl_response(
        "Pioneer Investment Services Co. v. Brunswick Associates Ltd. Partnership",
        snippet=(
            "The Court held that four factors govern excusable neglect: "
            "prejudice, length of delay, reason for delay, and good faith."
        ),
    )

    with patch(
        "backend.services.legal.cite_verifier.courtlistener_get",
        new_callable=AsyncMock,
        return_value=cl_response,
    ), patch(
        "backend.services.legal.cite_verifier.submit_chat_completion",
        new_callable=AsyncMock,
        return_value=_make_llm_response("SUPPORTS\nSnippet directly supports the proposition."),
    ):
        report = await verify_draft(
            SAMPLE_DRAFT,
            use_llm_extraction=False,  # Use regex only for speed
            use_llm_support_check=True,
        )

    assert isinstance(report, DraftVerificationReport)
    assert report.total_citations > 0, "Expected at least some citations in SAMPLE_DRAFT"
    # Pioneer should be found in CL mock
    pioneer_cites = [
        c for c in report.citations if "Pioneer" in c.raw or "507 U.S." in c.raw
    ]
    assert len(pioneer_cites) > 0, "Pioneer case should be extracted from SAMPLE_DRAFT"
    # Rule 3003 should be VERIFIED
    rule_cites = [c for c in report.citations if "3003" in c.raw]
    assert len(rule_cites) > 0, "Expected Fed R Bankr P 3003 to be extracted"
    assert rule_cites[0].level1_status == VerificationStatus.VERIFIED

    # Statutes should be UNCHECKABLE (not NOT_FOUND)
    statute_cites = [
        c for c in report.citations
        if c.citation_type == CitationType.FEDERAL_STATUTE
    ]
    for sc in statute_cites:
        assert sc.level1_status != VerificationStatus.NOT_FOUND, (
            f"USC title in valid range should not be NOT_FOUND: {sc.raw}"
        )

    # Corrected draft should not have NOT_FOUND markers (all are uncheckable/verified)
    assert "[CITATION FAILED VERIFICATION — NOT FOUND]" not in report.corrected_draft


# ---------------------------------------------------------------------------
# _apply_corrections unit tests
# ---------------------------------------------------------------------------

def test_apply_corrections_not_found() -> None:
    draft = "See Fake Co. v. No One, 1 F.3d 1 (2000). End."
    cite = CitationRecord(
        raw="Fake Co. v. No One, 1 F.3d 1 (2000)",
        citation_type=CitationType.FEDERAL_CASE,
        proposition="Something.",
        level1_status=VerificationStatus.NOT_FOUND,
        level2_text=None,
        level2_source_url=None,
        level3_status=VerificationStatus.UNCHECKABLE,
        final_status=VerificationStatus.NOT_FOUND,
        verification_notes="Not found",
    )
    corrected = _apply_corrections(draft, [cite])
    assert "[CITATION FAILED VERIFICATION — NOT FOUND]" in corrected
    assert "Fake Co." not in corrected


def test_apply_corrections_misquoted() -> None:
    raw = "Pioneer v. Brunswick, 507 U.S. 380 (1993)"
    draft = f"See {raw}. End."
    cite = CitationRecord(
        raw=raw,
        citation_type=CitationType.FEDERAL_CASE,
        proposition="Something.",
        level1_status=VerificationStatus.VERIFIED,
        level2_text="Some text.",
        level2_source_url="https://example.com",
        level3_status=VerificationStatus.MISQUOTED,
        final_status=VerificationStatus.MISQUOTED,
        verification_notes="Misquoted",
    )
    corrected = _apply_corrections(draft, [cite])
    assert "[CITE MAY NOT SUPPORT PROPOSITION — VERIFY]" in corrected
    assert raw in corrected  # cite kept, just flagged


def test_apply_corrections_verified_unchanged() -> None:
    raw = "28 U.S.C. § 157"
    draft = f"Under {raw}, this court has jurisdiction."
    cite = CitationRecord(
        raw=raw,
        citation_type=CitationType.FEDERAL_STATUTE,
        proposition="Jurisdiction.",
        level1_status=VerificationStatus.VERIFIED,
        level2_text=None,
        level2_source_url=None,
        level3_status=VerificationStatus.UNCHECKABLE,
        final_status=VerificationStatus.VERIFIED,
        verification_notes="Valid title",
    )
    corrected = _apply_corrections(draft, [cite])
    assert corrected == draft  # No changes
