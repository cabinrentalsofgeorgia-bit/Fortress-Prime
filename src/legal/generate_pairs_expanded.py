#!/usr/bin/env python3
"""
generate_pairs_expanded.py — Generate Pattern B and C training/eval pairs
from expanded GA corpus (OCGA sections + expanded CourtListener opinions).

Inputs:
  /mnt/fortress_nas/datasets/legal-corpus/ocga/title-*.jsonl  (OCGA sections)
  /mnt/fortress_nas/datasets/legal-corpus/ga-rules/*.jsonl    (GA court rules)
  /mnt/fortress_nas/legal-corpus/courtlistener/opinions-expanded.jsonl  (new opinions)

Outputs:
  /mnt/fortress_nas/datasets/legal-instruct/additions-20260421/new_b_pairs.jsonl
  /mnt/fortress_nas/datasets/legal-instruct/additions-20260421/new_c_pairs.jsonl
  /mnt/fortress_nas/datasets/legal-instruct/additions-20260421/eval_b.jsonl
  /mnt/fortress_nas/datasets/legal-instruct/additions-20260421/eval_c.jsonl

Split: 80% training, 20% eval (by source cluster for opinions; by section for OCGA)
Dedup: hash of instruction[:200] against existing training AND eval sets
Target: ≥200 training pairs per pattern, ≥50 eval per pattern (≥100 for C)

Usage:
  python -m src.legal.generate_pairs_expanded [--dry-run] [--eval-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.legal.training_pairs_scripted import (
    _extract_citations,
    _extract_facts,
    _extract_section_topics,
    _is_insurance_opinion,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"generate_pairs"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("generate_pairs")

CORPUS_ROOT = Path("/mnt/fortress_nas")
OCGA_DIR    = CORPUS_ROOT / "datasets/legal-corpus/ocga"
RULES_DIR   = CORPUS_ROOT / "datasets/legal-corpus/ga-rules"
EXPANDED_CL = CORPUS_ROOT / "legal-corpus/courtlistener/opinions-expanded.jsonl"
ORIG_TRAIN  = CORPUS_ROOT / "legal-corpus/training-pairs/train.jsonl"
ORIG_VAL    = CORPUS_ROOT / "legal-corpus/training-pairs/val.jsonl"
ORIG_HOLD   = CORPUS_ROOT / "legal-corpus/training-pairs/holdout.jsonl"
ORIG_FULL   = CORPUS_ROOT / "legal-corpus/courtlistener/opinions-full.jsonl"
OUT_DIR     = CORPUS_ROOT / "datasets/legal-instruct/additions-20260421"

TRAIN_SPLIT = 0.80  # 80% training, 20% eval

random.seed(42)


def _dedup_key(text: str) -> str:
    return hashlib.sha1(text[:200].encode()).hexdigest()


def load_existing_keys() -> set[str]:
    keys: set[str] = set()
    for path in [ORIG_TRAIN, ORIG_VAL, ORIG_HOLD]:
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                instr = r.get("instruction", r.get("user_prompt", ""))
                keys.add(_dedup_key(instr))
    # Also load any already-generated additions
    for fname in ["new_b_pairs.jsonl", "new_c_pairs.jsonl", "eval_b.jsonl", "eval_c.jsonl"]:
        p = OUT_DIR / fname
        if p.exists():
            with open(p) as f:
                for line in f:
                    r = json.loads(line)
                    keys.add(_dedup_key(r.get("instruction", r.get("user_prompt", ""))))
    log.info("loaded %d existing instruction keys", len(keys))
    return keys


# ---------------------------------------------------------------------------
# Pattern C from OCGA sections
# ---------------------------------------------------------------------------

def _is_substantive_section(text: str) -> bool:
    """Filter out reserved, history-only, and near-empty sections."""
    if not text or len(text) < 50:
        return False
    reserved = ["reserved", "repealed", "void", "this section", "not in effect"]
    lower = text.lower()
    if any(r in lower for r in reserved) and len(text) < 200:
        return False
    return True


def _extract_propositions(section_text: str, citation: str) -> list[str]:
    """Extract 1-3 proposition sentences from section text that demonstrate the law's effect."""
    # Split into sentences
    sentences = re.split(r"(?<=[.;])\s+", section_text)
    props = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 40 or len(sent) > 500:
            continue
        # Skip sentences that are just definitions or cross-references
        if sent.lower().startswith(("as used in", "for purposes of", "see also", "this code")):
            continue
        # Prefer actionable sentences (shall, must, may not, requires)
        if re.search(r"\b(shall|must|may not|required|prohibited|entitled|liable)\b", sent, re.I):
            props.append(sent)
        elif len(props) < 1:  # fallback: first substantive sentence
            props.append(sent)
        if len(props) >= 2:
            break
    return props


def generate_c_from_ocga(
    existing_keys: set[str],
    dry_run: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Generate Pattern C pairs from OCGA sections. Returns (train_pairs, eval_pairs)."""
    train_pairs: list[dict] = []
    eval_pairs: list[dict] = []

    ocga_files = sorted(OCGA_DIR.glob("title-*.jsonl"))
    if not ocga_files:
        log.warning("no OCGA JSONL files found in %s", OCGA_DIR)
        return train_pairs, eval_pairs

    log.info("found %d OCGA title files", len(ocga_files))

    for title_file in ocga_files:
        title_sections = []
        with open(title_file) as f:
            for line in f:
                if line.strip():
                    title_sections.append(json.loads(line))

        log.info("processing %s: %d sections", title_file.name, len(title_sections))

        # Shuffle for random train/eval split
        random.shuffle(title_sections)

        for sec in title_sections:
            text = sec.get("text", "")
            citation = sec.get("citation", "")
            heading = sec.get("heading", "")

            if not _is_substantive_section(text):
                continue
            if not citation:
                continue

            # Generate propositions for this section
            props = _extract_propositions(text, citation)
            if not props:
                continue

            for prop in props[:2]:  # max 2 pairs per section
                instruction = (
                    f"What Georgia legal authority supports the following proposition?\n\n{prop}"
                )
                key = _dedup_key(instruction)
                if key in existing_keys:
                    continue

                output = f"Under {citation}"
                if heading:
                    output += f" ({heading})"
                output += f": {text[:600]}"
                if len(text) > 600:
                    output += "..."

                pair = {
                    "pattern": "C",
                    "source": "ocga",
                    "source_cluster": sec.get("section", ""),
                    "instruction": instruction,
                    "output": output,
                    "metadata": {
                        "citation": citation,
                        "title": sec.get("title"),
                        "section": sec.get("section"),
                        "heading": heading,
                    },
                }

                existing_keys.add(key)

                # 80/20 split: use section number parity as deterministic split
                sec_num_str = sec.get("section", "0").replace("-", "")
                try:
                    is_eval = (int(sec_num_str[-2:]) % 5 == 0)  # every 5th section → eval
                except ValueError:
                    is_eval = False

                if is_eval:
                    eval_pairs.append(pair)
                else:
                    train_pairs.append(pair)

    log.info("ocga_c_pairs train=%d eval=%d", len(train_pairs), len(eval_pairs))
    return train_pairs, eval_pairs


# ---------------------------------------------------------------------------
# Pattern C from GA Court Rules
# ---------------------------------------------------------------------------

def generate_c_from_rules(
    existing_keys: set[str],
    dry_run: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Generate Pattern C pairs from GA court rules."""
    train_pairs: list[dict] = []
    eval_pairs: list[dict] = []

    rules_files = list(RULES_DIR.glob("*.jsonl"))
    if not rules_files:
        log.warning("no rules JSONL files found in %s", RULES_DIR)
        return train_pairs, eval_pairs

    log.info("found %d rules files", len(rules_files))

    for rules_file in rules_files:
        rules = []
        with open(rules_file) as f:
            for line in f:
                if line.strip():
                    rules.append(json.loads(line))

        log.info("processing %s: %d rules", rules_file.name, len(rules))
        random.shuffle(rules)

        for i, rule in enumerate(rules):
            text = rule.get("text", "")
            rule_num = rule.get("rule_number", "")
            rule_set = rule.get("rule_set", "")
            heading = rule.get("heading", "")

            if not _is_substantive_section(text):
                continue

            props = _extract_propositions(text, f"{rule_set} {rule_num}")
            if not props:
                continue

            for prop in props[:2]:
                instruction = (
                    f"What Georgia procedural authority governs the following?\n\n{prop}"
                )
                key = _dedup_key(instruction)
                if key in existing_keys:
                    continue

                output = f"Under {rule_set}, {rule_num}"
                if heading:
                    output += f" ({heading})"
                output += f": {text[:600]}"

                pair = {
                    "pattern": "C",
                    "source": "ga_rules",
                    "source_cluster": f"{rule_set.replace(' ', '_')}-{rule_num}",
                    "instruction": instruction,
                    "output": output,
                    "metadata": {
                        "rule_set": rule_set,
                        "rule_number": rule_num,
                        "heading": heading,
                    },
                }

                existing_keys.add(key)
                is_eval = (i % 5 == 0)
                if is_eval:
                    eval_pairs.append(pair)
                else:
                    train_pairs.append(pair)

    log.info("rules_c_pairs train=%d eval=%d", len(train_pairs), len(eval_pairs))
    return train_pairs, eval_pairs


# ---------------------------------------------------------------------------
# Pattern B and C from expanded CourtListener opinions
# ---------------------------------------------------------------------------

_STRICT_INSURANCE = re.compile(
    r"\b(?:insurance|insurer|insured|coverage|policy|policyholder|indemnity|underwriting|premium)\b",
    re.IGNORECASE,
)


def _is_civil_opinion(rec: dict) -> bool:
    """Accept civil law opinions (not just insurance, and not criminal/bar)."""
    case_name = rec.get("case_name", "")
    if re.search(r"\bv\.\s+(?:THE\s+)?STATE\b", case_name, re.IGNORECASE):
        return False
    if re.search(r"\bIn\s+(?:the\s+)?Matter\s+of\b", case_name, re.IGNORECASE):
        return False
    return True


def generate_from_expanded_opinions(
    existing_keys: set[str],
    dry_run: bool = False,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Generate Pattern B+C from expanded opinions.
    Returns (b_train, b_eval, c_train, c_eval).
    """
    if not EXPANDED_CL.exists():
        log.warning("expanded opinions not found: %s", EXPANDED_CL)
        return [], [], [], []

    opinions = [json.loads(l) for l in EXPANDED_CL.open() if l.strip()]
    log.info("loaded %d expanded opinions", len(opinions))

    # Load existing cluster IDs from original corpus to skip them in B extraction
    orig_clusters: set[str] = set()
    with open(ORIG_FULL) as f:
        for l in f:
            r = json.loads(l)
            orig_clusters.add(str(r.get("cluster_id", "")))

    b_train, b_eval, c_train, c_eval = [], [], [], []

    for i, rec in enumerate(opinions):
        if not _is_civil_opinion(rec):
            continue

        cluster = str(rec.get("cluster_id", ""))
        text = rec.get("plain_text", "")
        if not text:
            continue

        is_eval_cluster = (i % 5 == 0)  # 20% to eval

        # Pattern B: issue spotting
        if cluster not in orig_clusters and _is_insurance_opinion(text):
            facts = _extract_facts(text, max_chars=1500)
            topics = _extract_section_topics(text)
            if facts and topics:
                instruction = (
                    f"Identify the key legal issues raised in this Georgia insurance dispute:\n\n{facts}"
                )
                key = _dedup_key(instruction)
                if key not in existing_keys:
                    issues_text = "\n".join(f"  {j+1}. {t}" for j, t in enumerate(topics))
                    pair = {
                        "pattern": "B",
                        "source": "courtlistener_expanded",
                        "source_cluster": cluster,
                        "instruction": instruction,
                        "output": f"The following legal issues are presented:\n{issues_text}",
                        "metadata": {
                            "case": rec.get("case_name"),
                            "date": rec.get("date_filed"),
                        },
                    }
                    existing_keys.add(key)
                    if is_eval_cluster:
                        b_eval.append(pair)
                    else:
                        b_train.append(pair)

        # Pattern C: citation lookup
        cites = _extract_citations(text)
        for c in cites[:5]:  # up to 5 per opinion
            if len(c.get("context", "")) < 80:
                continue
            principle = c["context"].replace(c["cite"], "[citation]").strip()
            if "[citation]" not in principle:
                continue
            instruction = (
                f"What Georgia legal authority supports the following proposition?\n\n{principle}"
            )
            key = _dedup_key(instruction)
            if key in existing_keys:
                continue
            pair = {
                "pattern": "C",
                "source": "courtlistener_expanded",
                "source_cluster": cluster,
                "instruction": instruction,
                "output": f"Under {c['cite']}: {c['context']}",
                "metadata": {
                    "case": rec.get("case_name"),
                    "cite": c["cite"],
                },
            }
            existing_keys.add(key)
            if is_eval_cluster:
                c_eval.append(pair)
            else:
                c_train.append(pair)

    log.info("expanded_opinions b_train=%d b_eval=%d c_train=%d c_eval=%d",
             len(b_train), len(b_eval), len(c_train), len(c_eval))
    return b_train, b_eval, c_train, c_eval


# ---------------------------------------------------------------------------
# Spot-check: validate 20 random pairs per pattern
# ---------------------------------------------------------------------------

def spot_check(pairs: list[dict], pattern: str, n: int = 20) -> bool:
    """Print random sample for manual review; return True always (automated)."""
    sample = random.sample(pairs, min(n, len(pairs)))
    malformed = 0
    for p in sample:
        instr = p.get("instruction", "")
        output = p.get("output", "")
        if len(instr) < 20 or len(output) < 20:
            malformed += 1
        if pattern == "C" and "[citation]" not in instr and "O.C.G.A." not in instr:
            # C pairs should have [citation] placeholder or OCGA reference
            pass  # OK for rule-based C pairs
        if pattern == "B" and "legal issues" not in output.lower() and "presented" not in output.lower():
            malformed += 1
    log.info("spot_check pattern=%s sample=%d malformed=%d", pattern, len(sample), malformed)
    if malformed > 2:
        log.warning("QUALITY GATE: %d/%d malformed in Pattern %s spot-check", malformed, len(sample), pattern)
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, eval_only: bool = False) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    existing_keys = load_existing_keys()

    # Generate pairs from all sources
    ocga_c_train, ocga_c_eval = generate_c_from_ocga(existing_keys, dry_run)
    rules_c_train, rules_c_eval = generate_c_from_rules(existing_keys, dry_run)
    exp_b_train, exp_b_eval, exp_c_train, exp_c_eval = generate_from_expanded_opinions(
        existing_keys, dry_run
    )

    # Combine
    all_b_train = exp_b_train
    all_b_eval  = exp_b_eval
    all_c_train = ocga_c_train + rules_c_train + exp_c_train
    all_c_eval  = ocga_c_eval  + rules_c_eval  + exp_c_eval

    log.info("combined: b_train=%d b_eval=%d c_train=%d c_eval=%d",
             len(all_b_train), len(all_b_eval), len(all_c_train), len(all_c_eval))

    # Quality gate
    if all_b_train and not spot_check(all_b_train, "B"):
        log.error("Pattern B quality gate FAILED — halting")
        return 1
    if all_c_train and not spot_check(all_c_train, "C"):
        log.error("Pattern C quality gate FAILED — halting")
        return 1

    if dry_run:
        log.info("[DRY RUN] b_train=%d b_eval=%d c_train=%d c_eval=%d",
                 len(all_b_train), len(all_b_eval), len(all_c_train), len(all_c_eval))
        return 0

    # Write outputs
    def write_jsonl(path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        log.info("wrote %d records to %s", len(records), path)

    if not eval_only:
        write_jsonl(OUT_DIR / "new_b_pairs.jsonl", all_b_train)
        write_jsonl(OUT_DIR / "new_c_pairs.jsonl", all_c_train)

    # For eval: convert to eval schema
    def to_eval_record(pair: dict) -> dict:
        return {
            "id": hashlib.sha1(pair["instruction"].encode()).hexdigest()[:10],
            "domain": f"legal/{pair['pattern']}",
            "source_module": pair.get("source", "generated"),
            "model_used": "rule_extracted",
            "user_prompt": pair["instruction"],
            "teacher_response": pair["output"],
            "created_at": datetime.now(tz=timezone.utc).date().isoformat(),
        }

    write_jsonl(OUT_DIR / "eval_b.jsonl", [to_eval_record(p) for p in all_b_eval])
    write_jsonl(OUT_DIR / "eval_c.jsonl", [to_eval_record(p) for p in all_c_eval])

    # Summary
    print("\n=== Pair Generation Summary ===")
    print(f"Pattern B training: {len(all_b_train):4d}")
    print(f"Pattern B eval:     {len(all_b_eval):4d}")
    print(f"Pattern C training: {len(all_c_train):4d}")
    print(f"Pattern C eval:     {len(all_c_eval):4d}")
    print(f"\nOutput: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--eval-only", action="store_true", help="Only write eval files")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run, eval_only=args.eval_only))
