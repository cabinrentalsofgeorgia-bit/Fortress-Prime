#!/usr/bin/env python3
"""
training_pairs_scripted.py — Phase 4d Part 2: Patterns A-D scripted pair extraction.

Generates instruction-tuning pairs from the Georgia insurance corpus without
invoking any LLM. Rule-based extraction over the 1,854 full-text opinions.

Patterns:
  A — Case analysis  : "Given these facts: ..."  →  court's holding/reasoning
  B — Issue spotting : "Identify legal issues: ..." → enumerated section topics
  C — Citation lookup: "What authority supports X?" → OCGA/case citation + context
  D — Precedent outcome: "What's the likely outcome?" → holding from matching case

Usage:
  python -m src.legal.training_pairs_scripted

Output: /mnt/fortress_nas/legal-corpus/training-pairs/scripted.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("training_pairs_scripted")

CORPUS_ROOT = Path(os.getenv("LEGAL_CORPUS_ROOT", "/mnt/fortress_nas/legal-corpus"))
FULLTEXT_PATH = CORPUS_ROOT / "courtlistener" / "opinions-full.jsonl"
OUT_PATH = CORPUS_ROOT / "training-pairs" / "scripted.jsonl"

# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

_HOLDING_MARKERS = re.compile(
    r'(?:We hold|we hold|We therefore hold|therefore hold|we conclude|We conclude'
    r'|the trial court did not err|the trial court erred'
    r'|judgment is affirmed|judgment is reversed|judgment affirmed|judgment reversed'
    r'|AFFIRMED|REVERSED|we affirm|we reverse|we affirm in part|we reverse in part)',
    re.IGNORECASE,
)

_OCGA_CITE = re.compile(r'O\.C\.G\.A\.?\s*§\s*[\d\-]+(?:[–\-][\d]+)*(?:\s*\([a-z\d]+\))?')
_CASE_CITE = re.compile(
    r'[A-Z][a-zA-Z &,\'.]+\s+v\.\s+[A-Z][a-zA-Z &,\'.]+,?\s*\d{2,3}\s+Ga\.?(?:\s+App\.?)?\s*\d+[^\(]{0,30}\(\d{4}\)'
)
_SECTION_HEADER = re.compile(
    r'\n\s*([IVX]+\.|[0-9]+\.)\s+([A-Z][A-Za-z ]{3,60})\s*\n'
)

_NOISE = re.compile(r'\s+')

# Shared insurance-defense keyword filter.
# An opinion must contain at least one of these to produce A/B/D pairs.
# Pattern C (citation lookup) is structural — no content filter needed.
_INSURANCE_KEYWORDS: tuple[str, ...] = (
    "insurance", "coverage", "policy", "insurer", "insured",
    "bad faith", "duty to defend", "subrogation",
    "policyholder", "underwriting", "premium", "claim",
    "indemnity", "indemnification", "uninsured", "underinsured",
    "uim", "first-party", "third-party", "coverage exclusion",
    "reservation of rights", "denial of claim",
)


def _is_insurance_opinion(text: str) -> bool:
    """Return True if the opinion is substantively about insurance."""
    lower = text.lower()
    return any(kw in lower for kw in _INSURANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Negative exclusion patterns — these case types contaminate the corpus
# even when they mention "insurance" incidentally.
# ---------------------------------------------------------------------------

_EXCLUDE_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^In\s+(?:re|the\s+matter\s+of)\s",          # Attorney/estate/guardianship
    r"\bBar\s+Rule\b|\bdisciplinary\b|\bdisbarred\b|\bsuspended\s+from\s+the\s+practice\b",
    r"\bguilty\s+plea\b|\bconvicted\s+of\b|\bsentenced\s+to\b",  # Criminal conviction
    r"\bchild\s+(?:support|custody|welfare|abuse)\b",              # Family/juvenile
    r"\bmurder\b|\bhomicide\b|\bdrug\s+trafficking\b|\bdrug\s+offense\b",  # Criminal
    r"\bInquiry\s+Concerning\s+(?:Judge|Magistrate)\b",            # Judicial conduct
    r"\bdivorce\b|\balimony\b|\bmarital\s+property\b|\bmarriage\s+dissolution\b",  # Family law
))

# Minimum chars to be considered a substantive opinion (not a one-para order)
_MIN_OPINION_CHARS = 3000

# ---------------------------------------------------------------------------
# Positive signal patterns — A and D require at least one of these to ensure
# the pair is truly about insurance defense reasoning, not just adjacent.
# ---------------------------------------------------------------------------

_INSURANCE_DEFENSE_SIGNALS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bcoverage\s+(?:dispute|question|issue|exclusion|denial)\b",
        r"\bbad\s+faith\b",
        r"\bduty\s+to\s+(?:defend|indemnify)\b",
        r"\breservation\s+of\s+rights\b",
        r"\buninsured\s+motorist\b|\bUIM\b",
        r"\bfirst[-\s]party\b|\bthird[-\s]party\b",
        r"\bsubrogation\b",
        r"\bdeclaratory\s+judgment\b",
        r"\bstacking\b",
        r"\bpolicy\s+(?:exclusion|limit|provision|language)\b",
        r"\binsurance\s+(?:claim|dispute|coverage|policy|contract)\b",
        r"\binsurer\s+(?:denied|refused|failed|breached)\b",
    )
)


def _is_excluded(case_name: str, text: str) -> bool:
    """Return True if this opinion should be excluded regardless of insurance keywords."""
    check = (case_name or "") + " " + (text or "")[:2000]
    return any(p.search(check) for p in _EXCLUDE_PATTERNS)


def _has_defense_signal(text: str) -> bool:
    """Return True if the opinion has a strong insurance-defense signal."""
    return any(p.search(text or "") for p in _INSURANCE_DEFENSE_SIGNALS)


def _clean(text: str) -> str:
    return _NOISE.sub(' ', text).strip()


def _trim_to_sentence(text: str, max_chars: int = 2000) -> str:
    """Trim text to last complete sentence at or before max_chars."""
    if len(text) <= max_chars:
        return text
    chunk = text[:max_chars]
    for i in range(len(chunk) - 1, max_chars // 2, -1):
        if chunk[i] in '.!?' and (i + 1 >= len(chunk) or chunk[i + 1] in ' \n\t"\''):
            return chunk[:i + 1]
    return chunk


def _extract_facts(text: str, max_chars: int = 2000) -> str:
    """Extract procedural history + facts (typically the first 2000 chars after headers)."""
    # Strip notice/header boilerplate (Court of Appeals header, judge names)
    cleaned = re.sub(
        r'^[\s\S]{0,500}(?:Court of Appeals|SUPREME COURT)[^\n]*\n',
        '', text, count=1, flags=re.IGNORECASE
    )
    # Take first meaningful chunk
    facts = _clean(cleaned[:max_chars])
    return facts if len(facts) > 100 else _clean(text[:max_chars])


def _extract_holding(text: str) -> str:
    """Extract the court's holding(s), preserving complete sentences up to 2000 chars."""
    match = _HOLDING_MARKERS.search(text)
    if not match:
        # Fallback: last substantial paragraph
        paras = [p.strip() for p in text.split('\n\n') if p.strip()]
        for p in reversed(paras[-5:]):
            if len(p) > 50:
                return _trim_to_sentence(_clean(p), 2000)
        return ""
    # Take a 2500-char window from the marker, trim to last complete sentence
    window = _clean(text[match.start():match.start() + 2500])
    return _trim_to_sentence(window, 2000)


def _extract_section_topics(text: str) -> list[str]:
    """Extract Roman-numeral or numbered section headers as legal issues."""
    headers = _SECTION_HEADER.findall(text)
    topics = []
    for _, title in headers:
        title = title.strip().title()
        if title and len(title) > 3 and title.lower() not in ('background', 'facts', 'introduction', 'conclusion'):
            topics.append(title)
    return topics[:8]


def _extract_citations(text: str) -> list[dict[str, str]]:
    """Return list of {cite, context} dicts for OCGA and case citations."""
    cites = []
    # Find all citation positions
    for m in _OCGA_CITE.finditer(text):
        start = max(0, m.start() - 150)
        end = min(len(text), m.end() + 150)
        ctx = _clean(text[start:end])
        cite = m.group()
        # Extract the principle being cited for (sentence containing the cite)
        sentences = re.split(r'(?<=[.!?])\s+', ctx)
        for s in sentences:
            if cite in s and len(s) > 30:
                cites.append({"cite": cite, "context": _clean(s)[:300]})
                break
    for m in _CASE_CITE.finditer(text):
        # Find the sentence containing the citation by scanning back for a sentence boundary
        lookback = text[max(0, m.start() - 500):m.start()]
        sent_start = max(0, m.start() - 500)
        for sb in re.finditer(r'[.!?]\s+', lookback):
            sent_start = max(0, m.start() - 500) + sb.end()
        # Find sentence end after the citation
        lookahead = text[m.end():min(len(text), m.end() + 300)]
        sent_end = m.end()
        se = re.search(r'[.!?]', lookahead)
        if se:
            sent_end = m.end() + se.end()
        sentence = _clean(text[sent_start:sent_end])
        cite_text = _clean(m.group())
        context = sentence[:300] if len(sentence) >= 30 else _clean(text[max(0, m.start()-150):min(len(text), m.end()+100)])[:300]
        cites.append({"cite": cite_text, "context": context})

    # Deduplicate by cite string
    seen: set[str] = set()
    unique = []
    for c in cites:
        if c["cite"] not in seen:
            seen.add(c["cite"])
            unique.append(c)
    return unique[:10]


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------

def pattern_a(rec: dict) -> dict | None:
    """Pattern A — Case analysis pair."""
    text = rec.get("plain_text", "")
    if len(text) < _MIN_OPINION_CHARS:
        return None
    if _is_excluded(rec.get("case_name", ""), text):
        return None
    if not _is_insurance_opinion(text):
        return None
    if not _has_defense_signal(text):  # require strong signal, not just keyword
        return None
    facts = _extract_facts(text)
    holding = _extract_holding(text)
    if not facts or not holding or len(holding) < 30:
        return None
    case_ref = f"{rec.get('case_name', 'This case')}, {rec.get('court', 'Georgia')}, {rec.get('date_filed', '')}"
    return {
        "pattern": "A",
        "source_cluster": rec.get("cluster_id"),
        "instruction": (
            f"Given these facts from a Georgia insurance case, provide the applicable legal analysis:\n\n{facts}"
        ),
        "output": holding,
        "metadata": {"case": rec.get("case_name"), "date": rec.get("date_filed"), "ref": case_ref},
    }


def pattern_b(rec: dict) -> dict | None:
    """Pattern B — Issue spotting. Broader than A/D: any insurance keyword suffices."""
    text = rec.get("plain_text", "")
    if len(text) < _MIN_OPINION_CHARS:
        return None
    if _is_excluded(rec.get("case_name", ""), text):
        return None
    if not _is_insurance_opinion(text):
        return None
    facts = _extract_facts(text, max_chars=1500)
    topics = _extract_section_topics(text)
    if not facts or not topics:
        return None
    issues_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
    return {
        "pattern": "B",
        "source_cluster": rec.get("cluster_id"),
        "instruction": (
            f"Identify the key legal issues raised in this Georgia insurance dispute:\n\n{facts}"
        ),
        "output": f"The following legal issues are presented:\n{issues_text}",
        "metadata": {"case": rec.get("case_name"), "date": rec.get("date_filed")},
    }


def pattern_c(rec: dict) -> list[dict]:
    """Pattern C — Citation lookup. Length + exclusion filter; no positive signal required."""
    text = rec.get("plain_text", "")
    if len(text) < _MIN_OPINION_CHARS:
        return []
    if _is_excluded(rec.get("case_name", ""), text):
        return []
    cites = _extract_citations(text)
    pairs = []
    for c in cites[:3]:  # max 3 citation pairs per opinion
        if len(c["context"]) < 60:
            continue
        # Extract principle from context (remove the citation itself)
        principle = c["context"].replace(c["cite"], "[citation]").strip()
        pairs.append({
            "pattern": "C",
            "source_cluster": rec.get("cluster_id"),
            "instruction": (
                f"What Georgia legal authority supports the following proposition?\n\n{principle}"
            ),
            "output": f"Under {c['cite']}: {c['context']}",
            "metadata": {"case": rec.get("case_name"), "cite": c["cite"]},
        })
    return pairs


def pattern_d(rec: dict) -> dict | None:
    """Pattern D — Precedent outcome prediction."""
    text = rec.get("plain_text", "")
    if len(text) < _MIN_OPINION_CHARS:
        return None
    if _is_excluded(rec.get("case_name", ""), text):
        return None
    if not _is_insurance_opinion(text):
        return None
    if not _has_defense_signal(text):  # require strong signal
        return None
    facts = _extract_facts(text, max_chars=1800)
    holding = _extract_holding(text)
    if not facts or not holding or len(holding) < 40:
        return None
    court_short = rec.get("court", "Georgia Court").replace("Court of Appeals of Georgia", "Georgia Court of Appeals")
    return {
        "pattern": "D",
        "source_cluster": rec.get("cluster_id"),
        "instruction": (
            f"Based on similar Georgia precedent, what is the likely legal outcome for:\n\n{facts}\n\n"
            f"Provide analysis under Georgia insurance law."
        ),
        "output": (
            f"Under Georgia law, as demonstrated in {rec.get('case_name', 'similar precedent')} "
            f"({court_short}, {rec.get('date_filed', '')[:4]}): {holding}"
        ),
        "metadata": {"case": rec.get("case_name"), "date": rec.get("date_filed")},
    }


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def run_extraction() -> int:
    if not FULLTEXT_PATH.exists():
        log.error("Full-text corpus not found: %s", FULLTEXT_PATH)
        log.error("Run: python -m src.legal.corpus_ingest fetch-fulltext")
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    records = [json.loads(l) for l in FULLTEXT_PATH.open() if l.strip()]
    log.info("loaded %d opinions from corpus", len(records))

    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "total": 0}
    skipped = 0
    excluded = 0

    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(records):
            text = rec.get("plain_text", "")
            if not text:
                skipped += 1
                continue
            # Track exclusions separately for diagnostics
            if _is_excluded(rec.get("case_name", ""), text):
                excluded += 1

            pairs: list[dict] = []

            pa = pattern_a(rec)
            if pa:
                pairs.append(pa)
                counts["A"] += 1

            pb = pattern_b(rec)
            if pb:
                pairs.append(pb)
                counts["B"] += 1

            pairs.extend(pattern_c(rec))
            counts["C"] += len([p for p in pairs if p.get("pattern") == "C"])

            pd = pattern_d(rec)
            if pd:
                pairs.append(pd)
                counts["D"] += 1

            for p in pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
                counts["total"] += 1

            if (i + 1) % 200 == 0:
                log.info("progress %d/%d pairs_so_far=%d", i + 1, len(records), counts["total"])

    log.info(
        "extraction_complete total=%d A=%d B=%d C=%d D=%d skipped=%d excluded=%d out=%s",
        counts["total"], counts["A"], counts["B"], counts["C"], counts["D"],
        skipped, excluded, OUT_PATH,
    )
    print(f"\nScripted pairs written: {counts['total']:,}")
    print(f"  Pattern A (case analysis):    {counts['A']:,}")
    print(f"  Pattern B (issue spotting):   {counts['B']:,}")
    print(f"  Pattern C (citation lookup):  {counts['C']:,}")
    print(f"  Pattern D (precedent outcome):{counts['D']:,}")
    print(f"  Skipped (no text):            {skipped}")
    print(f"  Excluded (noise patterns):    {excluded}")
    print(f"Output: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(run_extraction())
