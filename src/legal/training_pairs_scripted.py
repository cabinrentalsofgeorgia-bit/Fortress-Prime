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
    r'|AFFIRMED|REVERSED|we affirm|we reverse|we affirm in part|we reverse in part)'
    r'[^\n]{0,400}',
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


def _clean(text: str) -> str:
    return _NOISE.sub(' ', text).strip()


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
    """Extract the court's holding(s)."""
    matches = _HOLDING_MARKERS.findall(text)
    if not matches:
        # Fallback: last paragraph before citations
        paras = [p.strip() for p in text.split('\n\n') if p.strip()]
        for p in reversed(paras[-5:]):
            if len(p) > 50:
                return _clean(p[:400])
        return ""
    # Take first holding that's substantive
    for m in matches:
        c = _clean(m)
        if len(c) > 40:
            return c[:500]
    return _clean(matches[0])[:500]


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
        start = max(0, m.start() - 150)
        end = min(len(text), m.end() + 100)
        ctx = _clean(text[start:end])
        cites.append({"cite": _clean(m.group()), "context": ctx[:300]})

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
    facts = _extract_facts(rec.get("plain_text", ""))
    holding = _extract_holding(rec.get("plain_text", ""))
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
    """Pattern B — Issue spotting."""
    facts = _extract_facts(rec.get("plain_text", ""), max_chars=1500)
    topics = _extract_section_topics(rec.get("plain_text", ""))
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
    """Pattern C — Citation lookup. May produce multiple pairs per opinion."""
    cites = _extract_citations(rec.get("plain_text", ""))
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
    facts = _extract_facts(rec.get("plain_text", ""), max_chars=1800)
    holding = _extract_holding(rec.get("plain_text", ""))
    if not facts or not holding or len(holding) < 40:
        return None
    # Only generate for cases with insurance-defense keywords in facts
    kws = ["insurance", "coverage", "policy", "insurer", "bad faith", "duty to defend", "subrogation"]
    if not any(k in facts.lower() for k in kws):
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

    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(records):
            if not rec.get("plain_text"):
                skipped += 1
                continue

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
        "extraction_complete total=%d A=%d B=%d C=%d D=%d skipped=%d out=%s",
        counts["total"], counts["A"], counts["B"], counts["C"], counts["D"],
        skipped, OUT_PATH,
    )
    print(f"\nScripted pairs written: {counts['total']:,}")
    print(f"  Pattern A (case analysis):    {counts['A']:,}")
    print(f"  Pattern B (issue spotting):   {counts['B']:,}")
    print(f"  Pattern C (citation lookup):  {counts['C']:,}")
    print(f"  Pattern D (precedent outcome):{counts['D']:,}")
    print(f"  Skipped (no text):            {skipped}")
    print(f"Output: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(run_extraction())
