"""
generate_b_pairs_v2.py — Improved Pattern B pair generation for Phase 3.

Addresses root causes identified in Phase 2 audit:
1. Gold answers are OCR-parsed section fragments — replace with normalized noun phrases
2. 37% single-topic gold answers — filter to opinions with ≥ 2 substantive topics
3. Fragment topics ("We Stated That", "Analysis") — clean extraction with length/form filters

Generates Pattern B pairs from the existing 1,854 GA insurance opinions with
improved topic extraction that produces clean, noun-phrase-format topic labels.

Target: ≥300 new pairs, each with 2-5 clean topics, deduplicated against
existing training + eval sets.

Output: /mnt/fortress_nas/datasets/legal-instruct/additions-20260422/new_b_pairs_v2.jsonl
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"gen_b_v2"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("gen_b_v2")

CORPUS_PATH = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-full.jsonl")
OUT_DIR     = Path("/mnt/fortress_nas/datasets/legal-instruct/additions-20260422")
OUT_PATH    = OUT_DIR / "new_b_pairs_v2.jsonl"

TRAIN_PATH  = Path("/mnt/fortress_nas/legal-corpus/training-pairs/train.jsonl")
HOLDOUT_PATH = Path("/mnt/fortress_nas/legal-corpus/training-pairs/holdout-eval-expanded-v2.json")
ADD_DIRS    = [
    Path("/mnt/fortress_nas/datasets/legal-instruct/additions-20260421"),
]

TARGET_PAIRS = 300

# ---------------------------------------------------------------------------
# Improved section topic extractor
# ---------------------------------------------------------------------------

_SECTION_HEADER_RE = re.compile(
    r"\n\s*([IVX]+\.?|[0-9]+\.)\s+([A-Z][A-Za-z\s\-\(\)]{3,60})\s*\n",
    re.MULTILINE,
)

_FILLER_TOPICS = re.compile(
    r"^(analysis|background|facts|introduction|conclusion|overview|"
    r"summary|discussion|procedural\s+history|the\s+court|we\s+hold|"
    r"we\s+state|it\s+is|in\s+conclusion|additionally|furthermore)$",
    re.IGNORECASE,
)

_FRAGMENT_RE = re.compile(r"^(we\s+|the\s+|a\s+|an\s+|this\s+|it\s+|that\s+|which\s+)", re.I)
_SENTENCE_ENDING = re.compile(r"[a-z]\s+[a-z].*[a-z]{3,}$")


def _clean_topic(raw: str) -> str | None:
    """Clean and validate a section header as a topic label."""
    t = re.sub(r"\s+", " ", raw).strip()
    t = re.sub(r"^[\d\.]+\s+", "", t)  # strip leading numbers

    # Length filter: 3-8 words is ideal
    words = t.split()
    if len(words) < 2 or len(words) > 10:
        return None

    # Filter filler/generic topics
    if _FILLER_TOPICS.match(t):
        return None

    # Filter sentence fragments (topic should be a noun phrase, not a sentence)
    if _FRAGMENT_RE.match(t) and _SENTENCE_ENDING.search(t):
        return None

    # Filter topics that are just the start of a sentence
    if t.endswith(("that", "the", "of", "in", "and", "or", "to", "a", "an")):
        return None

    # Filter all-caps headings that are just category labels
    if t.isupper() and len(words) == 1:
        return None

    # Normalize: title case, max 60 chars
    t = t.title()[:60].strip()
    return t if len(t) >= 8 else None


def extract_clean_topics(text: str) -> list[str]:
    """Extract clean topic labels from opinion text."""
    topics = []
    seen: set[str] = set()

    for m in _SECTION_HEADER_RE.finditer(text):
        raw = m.group(2).strip()
        cleaned = _clean_topic(raw)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            topics.append(cleaned)

    return topics[:8]  # max 8 topics per opinion


def _extract_facts(text: str, max_chars: int = 1500) -> str:
    """Extract case facts for the instruction."""
    cleaned = re.sub(r"^[\s\S]{0,500}(?:Court of Appeals|SUPREME COURT)[^\n]*\n",
                     "", text, count=1, flags=re.IGNORECASE)
    noise = re.compile(r"\s+")
    facts = noise.sub(" ", cleaned[:max_chars]).strip()
    return facts if len(facts) > 100 else noise.sub(" ", text[:max_chars]).strip()


_INSURANCE_KEYWORDS = frozenset([
    "insurance", "coverage", "policy", "insurer", "insured",
    "bad faith", "duty to defend", "subrogation", "indemnity",
])


def _is_insurance_opinion(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _INSURANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _instruction_key(text: str) -> str:
    return hashlib.sha1(text[:200].encode()).hexdigest()


def load_existing_keys() -> set[str]:
    keys: set[str] = set()
    for path in [TRAIN_PATH]:
        if not path.exists():
            continue
        with path.open() as f:
            for l in f:
                r = json.loads(l)
                keys.add(_instruction_key(r.get("instruction", r.get("user_prompt", ""))))

    if HOLDOUT_PATH.exists():
        data = json.loads(HOLDOUT_PATH.read_text())
        for r in data.get("records", []):
            keys.add(_instruction_key(r.get("user_prompt", "")))

    for d in ADD_DIRS:
        for fname in ["new_b_pairs.jsonl", "eval_b.jsonl"]:
            p = d / fname
            if not p.exists():
                continue
            with p.open() as f:
                for l in f:
                    if l.strip():
                        r = json.loads(l)
                        keys.add(_instruction_key(
                            r.get("instruction", r.get("user_prompt", ""))))

    log.info("loaded %d existing instruction keys", len(keys))
    return keys


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate(target: int = TARGET_PAIRS, dry_run: bool = False) -> int:
    if not CORPUS_PATH.exists():
        log.error("Corpus not found: %s", CORPUS_PATH)
        return 0

    existing_keys = load_existing_keys()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    opinions = [json.loads(l) for l in CORPUS_PATH.open() if l.strip()]
    log.info("Loaded %d opinions", len(opinions))

    generated = 0
    skipped_no_topics = 0
    skipped_dedup = 0
    skipped_no_insurance = 0

    out_fh = None if dry_run else OUT_PATH.open("w", encoding="utf-8")

    for rec in opinions:
        if generated >= target:
            break

        text = rec.get("plain_text", "")
        if not text or not _is_insurance_opinion(text):
            skipped_no_insurance += 1
            continue

        topics = extract_clean_topics(text)
        if len(topics) < 2:
            skipped_no_topics += 1
            continue

        facts = _extract_facts(text)
        if len(facts) < 100:
            continue

        instruction = (
            f"Identify the key legal issues raised in this Georgia insurance dispute:"
            f"\n\n{facts}"
        )
        key = _instruction_key(instruction)
        if key in existing_keys:
            skipped_dedup += 1
            continue

        issues_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
        pair = {
            "pattern": "B",
            "source_cluster": str(rec.get("cluster_id", "")),
            "instruction": instruction,
            "output": f"The following legal issues are presented:\n{issues_text}",
            "metadata": {
                "case": rec.get("case_name", ""),
                "date": rec.get("date_filed", ""),
                "n_topics": len(topics),
                "generator": "generate_b_pairs_v2",
            },
        }

        existing_keys.add(key)
        if not dry_run and out_fh:
            out_fh.write(json.dumps(pair, ensure_ascii=False) + "\n")
        generated += 1

        if generated % 50 == 0:
            log.info("generated=%d skipped_dedup=%d skipped_no_topics=%d",
                     generated, skipped_dedup, skipped_no_topics)

    if out_fh:
        out_fh.close()

    log.info(
        "complete: generated=%d target=%d skipped_no_insurance=%d "
        "skipped_no_topics=%d skipped_dedup=%d",
        generated, target, skipped_no_insurance, skipped_no_topics, skipped_dedup,
    )
    if not dry_run:
        log.info("output: %s", OUT_PATH)

    return generated


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=TARGET_PAIRS)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    n = generate(target=args.target, dry_run=args.dry_run)
    print(f"\nGenerated: {n} Pattern B pairs")
    if not args.dry_run:
        print(f"Output: {OUT_PATH}")
