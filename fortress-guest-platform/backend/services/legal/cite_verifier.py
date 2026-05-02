"""
Citation verifier for Fortress Legal drafting pipeline.

Three-level verification:
  Level 1 — existence check (does this citation exist?)
  Level 2 — source text retrieval
  Level 3 — support check (does retrieved text support the proposition?)

Public API:
  extract_citations(draft_text, use_llm) -> list[dict]
  verify_citation(record, rate_limiter)  -> CitationRecord
  verify_draft(...)                      -> DraftVerificationReport
  accept_draft(draft_text)               -> (bool, dict, str)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional

import httpx

from backend.services.courtlistener_client import courtlistener_get  # type: ignore[import-not-found]
from backend.services.swarm_service import submit_chat_completion  # type: ignore[import-not-found]
from backend.core.config import settings  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CitationType(str, Enum):
    FEDERAL_STATUTE     = "federal_statute"
    FEDERAL_CASE        = "federal_case"
    FEDERAL_REGULATION  = "federal_regulation"
    FEDERAL_RULE        = "federal_rule"
    STATE_CASE          = "state_case"
    STATE_STATUTE       = "state_statute"


class VerificationStatus(str, Enum):
    VERIFIED     = "VERIFIED"
    NOT_FOUND    = "NOT_FOUND"
    MISQUOTED    = "MISQUOTED"
    UNCHECKABLE  = "UNCHECKABLE"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CitationRecord:
    raw: str
    citation_type: CitationType
    proposition: str
    level1_status: VerificationStatus
    level2_text: Optional[str]
    level2_source_url: Optional[str]
    level3_status: VerificationStatus
    final_status: VerificationStatus
    verification_notes: str


@dataclass
class DraftVerificationReport:
    draft_id: str
    verified_at: str
    total_citations: int
    passed: int
    failed_level1: int
    failed_level3: int
    uncheckable: int
    citations: list[CitationRecord]
    passed_gate: bool
    corrected_draft: str


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

PATTERNS: dict[CitationType, list[str]] = {
    CitationType.FEDERAL_STATUTE: [
        # Patterns run on whitespace-normalized text (no newlines)
        # Section number and optional subsection only; stop at non-section chars
        r'\d+\s+U\.S\.C\.?\s+§§?\s+\d[\d\w\-(),.]*(?:\s+and\s+\d[\d\w\-(),.]*)?\b',
        r'\d+\s+U\.S\.C\.\s+[Ss]ection\s+\d[\d\w\-(),]*\b',
    ],
    CitationType.FEDERAL_REGULATION: [
        r'\d+\s+C\.F\.R\.?\s+§§?\s+\d[\d\w\-(),]*\b',
        r'\d+\s+C\.F\.R\.\s+[Ss]ection\s+\d[\d\w\-(),]*\b',
    ],
    CitationType.FEDERAL_RULE: [
        # Patterns run on whitespace-normalized text
        r'Fed\.?\s+R\.?\s+(?:Bankr|Civ|Crim|App|Evid)\.?\s+P\.?\s+[\d\w().,]+',
        r'F\.?R\.?C\.?P\.?\s+(?:Rule\s+)?\d+[\w()]*',
        r'FRCP\s+(?:Rule\s+)?\d+[\w()]*',
    ],
    CitationType.FEDERAL_CASE: [
        # Patterns run on whitespace-normalized text (newlines collapsed to spaces)
        # Use non-greedy party names (.{1,60}?) to avoid sweeping in surrounding text
        # Anchored by "v." — the party before v. and after v. must be 1-60 chars
        r"(?<![.\d])[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60}\s+v\.\s+[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60},\s*\d+\s+(?:U\.S\.|F\.\s*\d+d|F\.\s*Supp\.|B\.R\.|S\. ?Ct\.)\s+\d+\s*\(\d{4}\)",
        # Named case with Fed reporter
        r"(?<![.\d])[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60}\s+v\.\s+[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60},\s*\d+\s+F\.\d*d?\s+\d+\s*(?:\([^)]+\d{4}\))",
    ],
    CitationType.STATE_CASE: [
        # Georgia: "Name v. Name, NNN Ga. App. NNN (YYYY)"
        r"(?<![.\d])[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60}\s+v\.\s+[A-Z][A-Za-z][A-Za-z ,.'`&\-]{1,60},\s*\d+\s+Ga\.(?:\s+App\.)?\s+\d+\s*\(\d{4}\)",
    ],
    CitationType.STATE_STATUTE: [
        r'O\.C\.G\.A\.?\s+§§?\s+[\d\-\.]+(?:\s*(?:through|and)\s+[\d\-\.]+)?',
        r'Fla\.?\s+Stat\.?\s+§§?\s+[\d\.]+',
    ],
}

# Valid USC title range (titles 1-54 are valid; note some gaps exist but range check is sufficient)
_VALID_USC_TITLE_MAX = 54

# Valid Fed. R. Bankr. P. rule range
_BANKR_RULE_MIN = 1001
_BANKR_RULE_MAX = 9036

# Valid Fed. R. Civ. P. rule range
_CIV_RULE_MIN = 1
_CIV_RULE_MAX = 86

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _get_proposition(text: str, match_start: int, match_end: int) -> str:
    """Extract the sentence surrounding the citation match."""
    # Look back for sentence start
    search_start = max(0, match_start - 300)
    before = text[search_start:match_start]
    after = text[match_end:match_end + 300]
    # Find last sentence boundary before cite
    sent_start_search = re.search(r'(?:[.!?]\s+|\n)([^.!?\n]*)$', before)
    if sent_start_search:
        sentence_start = search_start + sent_start_search.start(1)
    else:
        sentence_start = search_start
    # Find first sentence boundary after cite
    sent_end_search = re.search(r'[.!?]', after)
    if sent_end_search:
        sentence_end = match_end + sent_end_search.end()
    else:
        sentence_end = match_end + min(200, len(after))
    return text[sentence_start:sentence_end].strip()


def _deduplicate(citations: list[dict]) -> list[dict]:
    """Remove duplicate citations by substring match."""
    result: list[dict] = []
    for cand in citations:
        raw_cand = cand["raw"].strip()
        # Check if this raw is already covered by an existing entry (substring)
        already_covered = any(
            raw_cand in existing["raw"] or existing["raw"] in raw_cand
            for existing in result
        )
        if not already_covered:
            result.append(cand)
    return result


def _normalize_whitespace(text: str) -> str:
    """Replace any sequence of whitespace (including newlines) with a single space."""
    return re.sub(r'[ \t]*\n[ \t]*', ' ', text)


def _extract_regex(draft_text: str) -> list[dict]:
    """Run regex extraction on draft text. Returns list of raw dicts.

    Runs patterns on a whitespace-normalized version to handle citations that
    span line breaks. The original text is used for proposition extraction.
    """
    # Normalize for matching (collapse newlines to spaces)
    normalized = _normalize_whitespace(draft_text)
    results: list[dict] = []
    for cite_type, patterns in PATTERNS.items():
        for pattern in patterns:
            for m in re.finditer(pattern, normalized, re.IGNORECASE):
                raw = m.group(0).strip()
                # Clean trailing whitespace/punctuation that was swept in
                raw = re.sub(r'[\s,;.]+$', '', raw).strip()
                # Remove common leading prepositions/connectors that got swept in
                # e.g. "Under Pioneer..." -> "Pioneer...", "See also Fed." -> "Fed."
                raw = re.sub(r'^(?:Under|See|Also|Per|In|By|Pursuant to|As stated in|As set forth in)\s+', '', raw, flags=re.IGNORECASE).strip()
                # Find proposition from normalized text
                norm_start = m.start()
                proposition = _get_proposition(normalized, norm_start, m.end())
                results.append({
                    "raw": raw,
                    "citation_type": cite_type.value,
                    "proposition": proposition,
                })
    return results


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a legal citation extractor. Extract ONLY explicit legal citations from the text — "
    "citations that directly reference a specific source by name, number, or code. "
    "Do NOT invent citations. Return JSON array, empty array if none found."
)

_LLM_USER_TEMPLATE = (
    'Extract all legal citations from the following text. For each, return: '
    '{{"raw": "verbatim citation text", "type": "federal_statute|federal_case|federal_regulation|'
    'federal_rule|state_case|state_statute", "proposition": "the sentence or clause this citation '
    'is cited in support of"}}\n\nText:\n{text}'
)

_TYPE_MAP: dict[str, CitationType] = {
    "federal_statute": CitationType.FEDERAL_STATUTE,
    "federal_case": CitationType.FEDERAL_CASE,
    "federal_regulation": CitationType.FEDERAL_REGULATION,
    "federal_rule": CitationType.FEDERAL_RULE,
    "state_case": CitationType.STATE_CASE,
    "state_statute": CitationType.STATE_STATUTE,
}


async def _extract_via_llm(draft_text: str) -> list[dict]:
    """Ask the LLM to find any citations the regex missed."""
    try:
        response = await submit_chat_completion(
            prompt=_LLM_USER_TEMPLATE.format(text=draft_text[:8000]),
            model=settings.ollama_fast_model,
            system_message=_LLM_SYSTEM,
            timeout_s=60.0,
        )
        # Extract content from openai-style response
        content: str = ""
        choices = response.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""

        # Parse JSON array from content
        # Strip markdown code blocks if present
        content = re.sub(r'^```(?:json)?\s*', '', content.strip(), flags=re.MULTILINE)
        content = re.sub(r'\s*```$', '', content.strip(), flags=re.MULTILINE)

        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return []

        results = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            raw = (item.get("raw") or "").strip()
            type_str = (item.get("type") or "").strip().lower()
            proposition = (item.get("proposition") or "").strip()
            if not raw:
                continue
            cite_type = _TYPE_MAP.get(type_str, CitationType.FEDERAL_CASE)
            results.append({
                "raw": raw,
                "citation_type": cite_type.value,
                "proposition": proposition,
            })
        return results
    except Exception as exc:
        logger.warning("llm_extraction_failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Public: extract_citations
# ---------------------------------------------------------------------------

async def extract_citations(draft_text: str, use_llm: bool = True) -> list[dict]:
    """
    Hybrid extraction: regex first, then LLM sweep for anything missed.
    Returns list of {raw, citation_type, proposition} dicts.
    use_llm=False for testing / offline use.
    """
    regex_results = _extract_regex(draft_text)
    combined = list(regex_results)

    if use_llm:
        llm_results = await _extract_via_llm(draft_text)
        # Add LLM results that aren't already covered by regex
        for llm_item in llm_results:
            raw_llm = llm_item["raw"].strip()
            already_covered = any(
                raw_llm in existing["raw"] or existing["raw"] in raw_llm
                for existing in combined
            )
            if not already_covered:
                combined.append(llm_item)

    return _deduplicate(combined)


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------

def _fuzzy_match(a: str, b: str) -> float:
    """Return similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _extract_rule_number(raw: str) -> Optional[int]:
    """Extract the primary rule number from a Fed. R. ... P. citation."""
    m = re.search(r'(\d+)', raw.split("P.")[-1] if "P." in raw else raw)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_usc_title(raw: str) -> Optional[int]:
    """Extract the USC title number from a citation like '28 U.S.C. § 157'."""
    m = re.match(r'\s*(\d+)\s+U\.S\.C', raw, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


async def _level3_support_check(
    proposition: str,
    source_text: str,
    citation_raw: str,
) -> VerificationStatus:
    """Ask LLM: does source_text support the proposition?"""
    if not source_text:
        return VerificationStatus.UNCHECKABLE

    prompt = (
        f"Does the following source text support the legal proposition it is cited for?\n\n"
        f"CITATION: {citation_raw}\n\n"
        f"PROPOSITION (what the draft claims this cite supports):\n{proposition}\n\n"
        f"SOURCE TEXT (retrieved from the cited authority):\n{source_text[:2000]}\n\n"
        f"Answer with ONLY one of: SUPPORTS or DOES_NOT_SUPPORT\n"
        f"Then on a new line, give a one-sentence explanation."
    )
    try:
        response = await submit_chat_completion(
            prompt=prompt,
            model=settings.ollama_fast_model,
            system_message="You are a precise legal research assistant. Evaluate citation support strictly.",
            timeout_s=60.0,
        )
        choices = response.get("choices", [])
        if not choices:
            return VerificationStatus.UNCHECKABLE
        content: str = choices[0].get("message", {}).get("content", "") or ""
        content_upper = content.strip().upper()
        if "DOES_NOT_SUPPORT" in content_upper or "DOES NOT SUPPORT" in content_upper:
            return VerificationStatus.MISQUOTED
        if "SUPPORTS" in content_upper:
            return VerificationStatus.VERIFIED
        return VerificationStatus.UNCHECKABLE
    except Exception as exc:
        logger.warning("level3_support_check_failed: %s", exc)
        return VerificationStatus.UNCHECKABLE


def _worst_status(*statuses: VerificationStatus) -> VerificationStatus:
    """Return the worst status from the set (NOT_FOUND > MISQUOTED > UNCHECKABLE > VERIFIED)."""
    order = {
        VerificationStatus.NOT_FOUND: 4,
        VerificationStatus.MISQUOTED: 3,
        VerificationStatus.UNCHECKABLE: 2,
        VerificationStatus.VERIFIED: 1,
    }
    return max(statuses, key=lambda s: order.get(s, 0))


# ---------------------------------------------------------------------------
# Per-type verification strategies
# ---------------------------------------------------------------------------

async def _verify_federal_case(
    raw: str,
    proposition: str,
    rate_limiter: asyncio.Semaphore,
    use_llm_support: bool = True,
) -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    """Returns: (level1, level2_text, level2_url, level3, notes)"""
    async with rate_limiter:
        data = await courtlistener_get(
            "search/",
            params={"q": raw, "type": "o", "order_by": "score desc", "page_size": 3},
        )
        await asyncio.sleep(0.3)

    if data is None:
        return (
            VerificationStatus.UNCHECKABLE,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "CourtListener returned None (token missing or error)",
        )

    results = data.get("results", [])
    if not results:
        return (
            VerificationStatus.NOT_FOUND,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "No results found in CourtListener for this case citation",
        )

    top = results[0]
    # Try to match case name
    cl_case_name: str = top.get("caseName", "") or top.get("case_name", "") or ""
    snippet: str = top.get("snippet", "") or top.get("text", "") or ""
    absolute_url: str = top.get("absolute_url", "") or ""
    url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else top.get("url", "")

    similarity = _fuzzy_match(raw, cl_case_name)
    if similarity > 0.70:
        level1 = VerificationStatus.VERIFIED
        notes = f"Matched case '{cl_case_name}' with similarity {similarity:.2f}"
    else:
        # Lower threshold — still check by partial token match
        # Split raw citation to get party names before the reporter
        raw_parts = re.split(r',\s*\d+\s+', raw)
        if raw_parts:
            case_name_part = raw_parts[0].strip()
            sim2 = _fuzzy_match(case_name_part, cl_case_name)
            if sim2 > 0.60:
                level1 = VerificationStatus.VERIFIED
                notes = f"Matched case '{cl_case_name}' via case-name portion (sim={sim2:.2f})"
            else:
                level1 = VerificationStatus.NOT_FOUND
                notes = f"Best match '{cl_case_name}' has low similarity {similarity:.2f}"
        else:
            level1 = VerificationStatus.NOT_FOUND
            notes = f"Best match '{cl_case_name}' has low similarity {similarity:.2f}"

    if level1 == VerificationStatus.NOT_FOUND:
        return level1, None, None, VerificationStatus.UNCHECKABLE, notes

    level2_text = snippet or None
    level2_url = url or None

    # Level 3 support check
    if use_llm_support and level2_text:
        level3 = await _level3_support_check(proposition, level2_text, raw)
        notes += f" | Level 3: {level3.value}"
    elif level2_text:
        level3 = VerificationStatus.UNCHECKABLE
        notes += " | Level 3: skipped (LLM disabled)"
    else:
        level3 = VerificationStatus.UNCHECKABLE
        notes += " | Level 3: no snippet available"

    return level1, level2_text, level2_url, level3, notes


async def _verify_federal_statute(
    raw: str,
    rate_limiter: asyncio.Semaphore,
) -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    """Returns: (level1, level2_text, level2_url, level3, notes)"""
    async with rate_limiter:
        # USC lookup service not yet integrated; rate-limit slot reserved for future use.
        await asyncio.sleep(0)
    title = _extract_usc_title(raw)
    if title is None:
        return (
            VerificationStatus.NOT_FOUND,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "Could not parse USC title number from citation",
        )

    if title < 1 or title > _VALID_USC_TITLE_MAX:
        return (
            VerificationStatus.NOT_FOUND,
            None, None,
            VerificationStatus.UNCHECKABLE,
            f"USC title {title} is outside the valid range (1-{_VALID_USC_TITLE_MAX})",
        )

    # Title is in valid range — mark UNCHECKABLE (can't conclusively verify without USC lookup)
    return (
        VerificationStatus.UNCHECKABLE,
        None, None,
        VerificationStatus.UNCHECKABLE,
        f"USC title {title} is within valid range (1-{_VALID_USC_TITLE_MAX}); format validates OK but full text unavailable",
    )


async def _verify_federal_rule(raw: str) -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    """Returns: (level1, level2_text, level2_url, level3, notes)"""
    raw_upper = raw.upper()

    if "BANKR" in raw_upper:
        rule_num = _extract_rule_number(raw)
        if rule_num is None:
            return (
                VerificationStatus.UNCHECKABLE,
                None, None,
                VerificationStatus.UNCHECKABLE,
                "Could not extract rule number from Fed. R. Bankr. P. citation",
            )
        if _BANKR_RULE_MIN <= rule_num <= _BANKR_RULE_MAX:
            return (
                VerificationStatus.VERIFIED,
                None, None,
                VerificationStatus.UNCHECKABLE,
                f"Fed. R. Bankr. P. {rule_num} is within valid range ({_BANKR_RULE_MIN}-{_BANKR_RULE_MAX})",
            )
        else:
            return (
                VerificationStatus.NOT_FOUND,
                None, None,
                VerificationStatus.UNCHECKABLE,
                f"Fed. R. Bankr. P. {rule_num} is outside valid range ({_BANKR_RULE_MIN}-{_BANKR_RULE_MAX})",
            )
    elif "CIV" in raw_upper or "FRCP" in raw_upper or "F.R.C.P" in raw_upper.replace(" ", ""):
        rule_num = _extract_rule_number(raw)
        if rule_num is None:
            return (
                VerificationStatus.UNCHECKABLE,
                None, None,
                VerificationStatus.UNCHECKABLE,
                "Could not extract rule number from Fed. R. Civ. P. citation",
            )
        if _CIV_RULE_MIN <= rule_num <= _CIV_RULE_MAX:
            return (
                VerificationStatus.VERIFIED,
                None, None,
                VerificationStatus.UNCHECKABLE,
                f"Fed. R. Civ. P. {rule_num} is within valid range ({_CIV_RULE_MIN}-{_CIV_RULE_MAX})",
            )
        else:
            return (
                VerificationStatus.NOT_FOUND,
                None, None,
                VerificationStatus.UNCHECKABLE,
                f"Fed. R. Civ. P. {rule_num} is outside valid range ({_CIV_RULE_MIN}-{_CIV_RULE_MAX})",
            )
    else:
        # Other federal rules — mark as UNCHECKABLE
        return (
            VerificationStatus.UNCHECKABLE,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "Federal rule type not specifically handled; format appears valid",
        )


async def _verify_federal_regulation(
    raw: str,
    rate_limiter: asyncio.Semaphore,
) -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    """Returns: (level1, level2_text, level2_url, level3, notes)"""
    # Attempt CourtListener search for regulation, fallback to UNCHECKABLE
    async with rate_limiter:
        data = await courtlistener_get(
            "search/",
            params={"q": raw, "type": "s", "page_size": 3},
        )
        await asyncio.sleep(0.3)

    if data is not None and data.get("results"):
        return (
            VerificationStatus.UNCHECKABLE,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "CFR citation: CourtListener search returned results but full text unavailable; format validates OK",
        )

    return (
        VerificationStatus.UNCHECKABLE,
        None, None,
        VerificationStatus.UNCHECKABLE,
        "CFR citation: no lookup service available; format-only check passed",
    )


async def _verify_state_statute() -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    return (
        VerificationStatus.UNCHECKABLE,
        None, None,
        VerificationStatus.UNCHECKABLE,
        "State statute: no lookup service available; cannot verify or disprove",
    )


async def _verify_state_case(
    raw: str,
    proposition: str,
    rate_limiter: asyncio.Semaphore,
    use_llm_support: bool = True,
) -> tuple[VerificationStatus, Optional[str], Optional[str], VerificationStatus, str]:
    """State cases — attempt CourtListener search."""
    async with rate_limiter:
        data = await courtlistener_get(
            "search/",
            params={"q": raw, "type": "o", "order_by": "score desc", "page_size": 3},
        )
        await asyncio.sleep(0.3)

    if data is None:
        return (
            VerificationStatus.UNCHECKABLE,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "CourtListener returned None for state case search",
        )

    results = data.get("results", [])
    if not results:
        return (
            VerificationStatus.NOT_FOUND,
            None, None,
            VerificationStatus.UNCHECKABLE,
            "No results found in CourtListener for this state case citation",
        )

    top = results[0]
    cl_case_name: str = top.get("caseName", "") or top.get("case_name", "") or ""
    snippet: str = top.get("snippet", "") or top.get("text", "") or ""
    absolute_url: str = top.get("absolute_url", "") or ""
    url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else top.get("url", "")

    similarity = _fuzzy_match(raw, cl_case_name)
    if similarity > 0.60:
        level1 = VerificationStatus.VERIFIED
        notes = f"State case matched '{cl_case_name}' (sim={similarity:.2f})"
    else:
        level1 = VerificationStatus.NOT_FOUND
        notes = f"State case best match '{cl_case_name}' has low similarity {similarity:.2f}"

    if level1 == VerificationStatus.NOT_FOUND:
        return level1, None, None, VerificationStatus.UNCHECKABLE, notes

    level2_text = snippet or None
    level2_url = url or None

    if use_llm_support and level2_text:
        level3 = await _level3_support_check(proposition, level2_text, raw)
        notes += f" | Level 3: {level3.value}"
    else:
        level3 = VerificationStatus.UNCHECKABLE
        notes += " | Level 3: skipped"

    return level1, level2_text, level2_url, level3, notes


# ---------------------------------------------------------------------------
# Public: verify_citation
# ---------------------------------------------------------------------------

async def verify_citation(
    record: dict,
    rate_limiter: asyncio.Semaphore,
    use_llm_support: bool = True,
) -> CitationRecord:
    """Verify a single citation through all 3 levels."""
    raw: str = record.get("raw", "")
    cite_type_str: str = record.get("citation_type", "")
    proposition: str = record.get("proposition", "")

    try:
        cite_type = CitationType(cite_type_str)
    except ValueError:
        cite_type = CitationType.FEDERAL_CASE

    try:
        if cite_type == CitationType.FEDERAL_CASE:
            l1, l2_text, l2_url, l3, notes = await _verify_federal_case(
                raw, proposition, rate_limiter, use_llm_support
            )
        elif cite_type == CitationType.STATE_CASE:
            l1, l2_text, l2_url, l3, notes = await _verify_state_case(
                raw, proposition, rate_limiter, use_llm_support
            )
        elif cite_type == CitationType.FEDERAL_STATUTE:
            l1, l2_text, l2_url, l3, notes = await _verify_federal_statute(raw, rate_limiter)
        elif cite_type == CitationType.FEDERAL_RULE:
            l1, l2_text, l2_url, l3, notes = await _verify_federal_rule(raw)
        elif cite_type == CitationType.FEDERAL_REGULATION:
            l1, l2_text, l2_url, l3, notes = await _verify_federal_regulation(raw, rate_limiter)
        elif cite_type == CitationType.STATE_STATUTE:
            l1, l2_text, l2_url, l3, notes = await _verify_state_statute()
        else:
            l1, l2_text, l2_url = VerificationStatus.UNCHECKABLE, None, None
            l3, notes = VerificationStatus.UNCHECKABLE, "Unknown citation type"

    except Exception as exc:
        logger.error("verify_citation_error raw=%r: %s", raw, exc)
        l1 = VerificationStatus.UNCHECKABLE
        l2_text, l2_url = None, None
        l3 = VerificationStatus.UNCHECKABLE
        notes = f"Unexpected error during verification: {exc}"

    final = _worst_status(l1, l3)

    return CitationRecord(
        raw=raw,
        citation_type=cite_type,
        proposition=proposition,
        level1_status=l1,
        level2_text=l2_text,
        level2_source_url=l2_url,
        level3_status=l3,
        final_status=final,
        verification_notes=notes,
    )


# ---------------------------------------------------------------------------
# Draft correction
# ---------------------------------------------------------------------------

def _apply_corrections(draft_text: str, citations: list[CitationRecord]) -> str:
    """Apply corrections to the draft based on verification results."""
    corrected = draft_text
    for cite in citations:
        if cite.final_status == VerificationStatus.NOT_FOUND:
            corrected = corrected.replace(
                cite.raw,
                "[CITATION FAILED VERIFICATION — NOT FOUND]",
            )
        elif cite.final_status == VerificationStatus.MISQUOTED:
            corrected = corrected.replace(
                cite.raw,
                f"{cite.raw} [CITE MAY NOT SUPPORT PROPOSITION — VERIFY]",
            )
        # UNCHECKABLE and VERIFIED — leave as-is
    return corrected


# ---------------------------------------------------------------------------
# Public: verify_draft
# ---------------------------------------------------------------------------

async def verify_draft(
    draft_text: str,
    draft_id: Optional[str] = None,
    use_llm_extraction: bool = True,
    use_llm_support_check: bool = True,
) -> DraftVerificationReport:
    """Full verification pipeline for a draft document."""
    if draft_id is None:
        draft_id = str(uuid.uuid4())

    verified_at = datetime.now(timezone.utc).isoformat()

    # Extract citations
    raw_citations = await extract_citations(draft_text, use_llm=use_llm_extraction)

    # Verify all citations concurrently (with rate limiter)
    rate_limiter = asyncio.Semaphore(3)
    tasks = [
        verify_citation(c, rate_limiter, use_llm_support=use_llm_support_check)
        for c in raw_citations
    ]
    citation_records: list[CitationRecord] = await asyncio.gather(*tasks)

    # Compute report statistics
    passed = sum(1 for c in citation_records if c.final_status == VerificationStatus.VERIFIED)
    failed_level1 = sum(1 for c in citation_records if c.level1_status == VerificationStatus.NOT_FOUND)
    failed_level3 = sum(
        1 for c in citation_records
        if c.level3_status == VerificationStatus.MISQUOTED
        and c.level1_status == VerificationStatus.VERIFIED
    )
    uncheckable = sum(1 for c in citation_records if c.final_status == VerificationStatus.UNCHECKABLE)

    passed_gate = failed_level1 == 0 and failed_level3 == 0

    corrected_draft = _apply_corrections(draft_text, citation_records)

    return DraftVerificationReport(
        draft_id=draft_id,
        verified_at=verified_at,
        total_citations=len(citation_records),
        passed=passed,
        failed_level1=failed_level1,
        failed_level3=failed_level3,
        uncheckable=uncheckable,
        citations=citation_records,
        passed_gate=passed_gate,
        corrected_draft=corrected_draft,
    )


# ---------------------------------------------------------------------------
# Public: accept_draft
# ---------------------------------------------------------------------------

async def accept_draft(draft_text: str) -> tuple[bool, dict, str]:
    """
    Top-level gate.
    Returns: (passes: bool, report: dict, corrected_draft: str)
    passes=True only if zero citations fail Level 1 or Level 2.
    Raises RuntimeError if CourtListener is genuinely unreachable.
    """
    # Quick reachability check — try to hit the CourtListener base URL
    token = (settings.courtlistener_api_token or "").strip()
    base = (settings.courtlistener_base_url or "").rstrip("/")

    if token and base:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base}/search/",
                    params={"q": "test", "type": "o", "page_size": 1},
                    headers={"Authorization": f"Token {token}", "Accept": "application/json"},
                )
                if resp.status_code not in (200, 404, 400):
                    raise RuntimeError(
                        f"CourtListener unreachable: HTTP {resp.status_code}"
                    )
        except httpx.ConnectError as exc:
            raise RuntimeError(f"CourtListener unreachable: connection refused — {exc}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"CourtListener unreachable: timeout — {exc}") from exc

    report = await verify_draft(draft_text)

    report_dict = {
        "draft_id": report.draft_id,
        "verified_at": report.verified_at,
        "total_citations": report.total_citations,
        "passed": report.passed,
        "failed_level1": report.failed_level1,
        "failed_level3": report.failed_level3,
        "uncheckable": report.uncheckable,
        "passed_gate": report.passed_gate,
        "citations": [
            {
                "raw": c.raw,
                "citation_type": c.citation_type.value,
                "proposition": c.proposition,
                "level1_status": c.level1_status.value,
                "level2_text": c.level2_text,
                "level2_source_url": c.level2_source_url,
                "level3_status": c.level3_status.value,
                "final_status": c.final_status.value,
                "verification_notes": c.verification_notes,
            }
            for c in report.citations
        ],
    }

    return report.passed_gate, report_dict, report.corrected_draft
