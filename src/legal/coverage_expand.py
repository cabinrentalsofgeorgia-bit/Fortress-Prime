#!/usr/bin/env python3
"""
coverage_expand.py — Phase 4d coverage gap remediation.

Extracts new Pattern B and C pairs from the courtlistener corpus that are
not already present in training or holdout sets (dedup on instruction prefix).

Outputs:
  CORPUS_ROOT/training-pairs/new_b_pairs.jsonl   — new Pattern B (training)
  CORPUS_ROOT/training-pairs/new_c_pairs.jsonl   — new Pattern C (training)
  CORPUS_ROOT/training-pairs/holdout-eval-expanded.json  — expanded eval holdout

Usage:
  python -m src.legal.coverage_expand [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.legal.training_pairs_scripted import (
    _extract_citations,
    _extract_facts,
    _extract_section_topics,
)

import re as _re

_INSURANCE_LEAD_RE = _re.compile(
    r"\b(?:insurance|insurer|insured|coverage|policy|policyholder|indemnity|underwriting|premium)\b",
    _re.IGNORECASE,
)


def _is_genuine_insurance_dispute(rec: dict) -> bool:
    """Stricter gate: requires insurance terms in the opening text, excludes criminal/bar cases."""
    case_name = rec.get("case_name", "")
    if _re.search(r"\bv\.\s+(?:THE\s+)?STATE\b", case_name, _re.IGNORECASE):
        return False
    if _re.search(r"\bIn\s+(?:the\s+)?Matter\s+of\b", case_name, _re.IGNORECASE):
        return False
    lead = (rec.get("plain_text", "") or "")[:500]
    return bool(_INSURANCE_LEAD_RE.search(lead))

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"coverage_expand"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("coverage_expand")

CORPUS_ROOT = Path("/mnt/fortress_nas/legal-corpus")
FULLTEXT_PATH = CORPUS_ROOT / "courtlistener" / "opinions-full.jsonl"
TRAIN_PATH    = CORPUS_ROOT / "training-pairs" / "train.jsonl"
VAL_PATH      = CORPUS_ROOT / "training-pairs" / "val.jsonl"
HOLDOUT_PATH  = CORPUS_ROOT / "training-pairs" / "holdout.jsonl"
HOLDOUT_EVAL  = CORPUS_ROOT / "training-pairs" / "holdout-eval.json"
NEW_B_OUT     = CORPUS_ROOT / "training-pairs" / "new_b_pairs.jsonl"
NEW_C_OUT     = CORPUS_ROOT / "training-pairs" / "new_c_pairs.jsonl"
EXPANDED_EVAL = CORPUS_ROOT / "training-pairs" / "holdout-eval-expanded.json"

# Dedup key: first 200 chars of the instruction / user_prompt
def _dedup_key(text: str) -> str:
    return text[:200]


def _load_existing_keys() -> tuple[set[str], set[str]]:
    """Return (existing_instruction_keys, holdout_clusters)."""
    keys: set[str] = set()
    holdout_clusters: set[str] = set()
    for path in [TRAIN_PATH, VAL_PATH, HOLDOUT_PATH]:
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                instr = r.get("instruction", r.get("user_prompt", ""))
                keys.add(_dedup_key(instr))
                if "holdout" in path.name:
                    holdout_clusters.add(str(r.get("source_cluster", "")))
    return keys, holdout_clusters


def _make_pattern_c(rec: dict, existing_keys: set[str]) -> list[dict]:
    """Extract Pattern C pairs from one opinion, skipping duplicates."""
    text = rec.get("plain_text", "")
    if not text:
        return []
    cites = _extract_citations(text)
    pairs = []
    for c in cites:
        ctx = c.get("context", "")
        if len(ctx) < 80:
            continue
        principle = ctx.replace(c["cite"], "[citation]").strip()
        if "[citation]" not in principle:
            continue
        instruction = f"What Georgia legal authority supports the following proposition?\n\n{principle}"
        key = _dedup_key(instruction)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        pairs.append({
            "pattern": "C",
            "source_cluster": str(rec.get("cluster_id", "")),
            "instruction": instruction,
            "output": f"Under {c['cite']}: {ctx}",
            "metadata": {
                "case": rec.get("case_name", ""),
                "cite": c["cite"],
                "date": rec.get("date_filed", ""),
            },
        })
    return pairs


def _make_pattern_b(rec: dict, existing_keys: set[str]) -> dict | None:
    """Extract one Pattern B pair from an opinion, skipping duplicates."""
    text = rec.get("plain_text", "")
    if not text:
        return None
    facts = _extract_facts(text, max_chars=1500)
    topics = _extract_section_topics(text)
    if not facts or not topics:
        return None
    instruction = f"Identify the key legal issues raised in this Georgia insurance dispute:\n\n{facts}"
    key = _dedup_key(instruction)
    if key in existing_keys:
        return None
    existing_keys.add(key)
    issues_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
    return {
        "pattern": "B",
        "source_cluster": str(rec.get("cluster_id", "")),
        "instruction": instruction,
        "output": f"The following legal issues are presented:\n{issues_text}",
        "metadata": {
            "case": rec.get("case_name", ""),
            "date": rec.get("date_filed", ""),
        },
    }


def _pair_to_eval_record(pair: dict) -> dict:
    """Convert a training pair dict to the eval holdout schema."""
    return {
        "id": hashlib.sha1(pair["instruction"].encode()).hexdigest()[:10],
        "domain": f"legal/{pair['pattern']}",
        "source_module": "legal_corpus",
        "model_used": "rule_extracted",
        "user_prompt": pair["instruction"],
        "teacher_response": pair["output"],
        "created_at": datetime.now(tz=timezone.utc).date().isoformat(),
    }


def run(dry_run: bool = False) -> int:
    log.info("loading existing instruction keys and holdout clusters")
    existing_keys, holdout_clusters = _load_existing_keys()
    log.info("existing_keys=%d holdout_clusters=%d", len(existing_keys), len(holdout_clusters))

    opinions = [json.loads(l) for l in FULLTEXT_PATH.open() if l.strip()]
    log.info("loaded %d opinions from corpus", len(opinions))

    new_b: list[dict] = []
    new_c: list[dict] = []

    for rec in opinions:
        cluster = str(rec.get("cluster_id", ""))

        # Skip opinions whose cluster is in the holdout — would pollute training
        if cluster in holdout_clusters:
            continue

        if _is_genuine_insurance_dispute(rec):
            pb = _make_pattern_b(rec, existing_keys)
            if pb:
                new_b.append(pb)

        for pc in _make_pattern_c(rec, existing_keys):
            new_c.append(pc)

    log.info("new_pattern_b=%d new_pattern_c=%d", len(new_b), len(new_c))

    if not new_b and not new_c:
        log.warning("no new pairs found — corpus may be exhausted")

    if dry_run:
        log.info("[DRY RUN] would write %d B + %d C pairs", len(new_b), len(new_c))
        _print_samples(new_b, new_c)
        return 0

    # Write training expansion files
    with NEW_B_OUT.open("w") as f:
        for p in new_b:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    log.info("wrote %d pairs to %s", len(new_b), NEW_B_OUT)

    with NEW_C_OUT.open("w") as f:
        for p in new_c:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    log.info("wrote %d pairs to %s", len(new_c), NEW_C_OUT)

    # Build expanded eval holdout
    base_eval = json.loads(HOLDOUT_EVAL.read_text())
    existing_eval_ids = {r["id"] for r in base_eval["records"]}

    added_eval = []
    for p in new_b + new_c:
        rec_eval = _pair_to_eval_record(p)
        if rec_eval["id"] not in existing_eval_ids:
            added_eval.append(rec_eval)
            existing_eval_ids.add(rec_eval["id"])

    expanded_records = base_eval["records"] + added_eval
    domain_counts = dict(Counter(r["domain"] for r in expanded_records))

    expanded = {
        "holdout_date": datetime.now(tz=timezone.utc).date().isoformat(),
        "built_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": str(HOLDOUT_EVAL),
        "note": "Expanded with new Pattern B/C pairs from coverage_expand.py",
        "total_holdout": len(expanded_records),
        "domain_counts": domain_counts,
        "records": expanded_records,
    }
    EXPANDED_EVAL.write_text(json.dumps(expanded, indent=2, ensure_ascii=False))
    log.info(
        "expanded_eval written total=%d added=%d domain_counts=%s",
        len(expanded_records), len(added_eval), json.dumps(domain_counts),
    )

    _print_summary(new_b, new_c, added_eval, domain_counts)
    return 0


def _print_samples(new_b: list[dict], new_c: list[dict]) -> None:
    for label, pairs in [("B", new_b[:2]), ("C", new_c[:2])]:
        for p in pairs:
            print(f"\n[Pattern {label}] {p['metadata'].get('case','?')}")
            print(f"  Q: {p['instruction'][:120]}...")
            print(f"  A: {p['output'][:80]}...")


def _print_summary(new_b: list, new_c: list, added_eval: list, domain_counts: dict) -> None:
    print("\n=== Coverage Expansion Summary ===")
    print(f"New Pattern B pairs (training): {len(new_b)}")
    print(f"New Pattern C pairs (training): {len(new_c)}")
    print(f"New eval records added:         {len(added_eval)}")
    print(f"\nExpanded eval domain counts: {json.dumps(domain_counts, indent=2)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run))
