#!/usr/bin/env python3
"""
training_pairs_consolidate.py — Phase 4d Part 2: merge + split + deduplicate.

Merges scripted.jsonl + godhead.jsonl → combined.jsonl
Then splits 80/10/10 into train/val/holdout.

Usage:
  python -m src.legal.training_pairs_consolidate
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("training_pairs_consolidate")

CORPUS_ROOT = Path(os.getenv("LEGAL_CORPUS_ROOT", "/mnt/fortress_nas/legal-corpus"))
PAIRS_DIR = CORPUS_ROOT / "training-pairs"
SCRIPTED = PAIRS_DIR / "scripted.jsonl"
GODHEAD = PAIRS_DIR / "godhead.jsonl"
COMBINED = PAIRS_DIR / "combined.jsonl"
TRAIN = PAIRS_DIR / "train.jsonl"
VAL = PAIRS_DIR / "val.jsonl"
HOLDOUT = PAIRS_DIR / "holdout.jsonl"

TRAIN_RATIO = 0.80
VAL_RATIO = 0.10
HOLDOUT_RATIO = 0.10
RANDOM_SEED = 42


def _fingerprint(pair: dict) -> str:
    """Stable hash for deduplication."""
    key = (pair.get("instruction", "") + pair.get("output", "")).lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def run() -> int:
    PAIRS_DIR.mkdir(parents=True, exist_ok=True)
    all_pairs: list[dict] = []

    for source_path in (SCRIPTED, GODHEAD):
        if not source_path.exists():
            log.warning("source not found, skipping: %s", source_path)
            continue
        n = 0
        for line in source_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                all_pairs.append(json.loads(line))
                n += 1
        log.info("loaded %d pairs from %s", n, source_path.name)

    if not all_pairs:
        log.error("No pairs found — run scripted and/or godhead extraction first")
        return 1

    # Deduplicate
    seen: set[str] = set()
    unique: list[dict] = []
    for p in all_pairs:
        fp = _fingerprint(p)
        if fp not in seen:
            seen.add(fp)
            unique.append(p)
    n_dupes = len(all_pairs) - len(unique)
    log.info("dedup: %d total → %d unique (%d duplicates removed)", len(all_pairs), len(unique), n_dupes)

    # Write combined
    with COMBINED.open("w", encoding="utf-8") as fh:
        for p in unique:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    log.info("combined.jsonl written: %d pairs", len(unique))

    # Shuffle + split
    rng = random.Random(RANDOM_SEED)
    shuffled = unique.copy()
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * TRAIN_RATIO)
    n_val = int(n * VAL_RATIO)
    n_holdout = n - n_train - n_val

    splits = {
        TRAIN: shuffled[:n_train],
        VAL: shuffled[n_train:n_train + n_val],
        HOLDOUT: shuffled[n_train + n_val:],
    }

    for path, pairs in splits.items():
        with path.open("w", encoding="utf-8") as fh:
            for p in pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        log.info("wrote %s: %d pairs", path.name, len(pairs))

    print(f"\nConsolidation complete:")
    print(f"  Total pairs:     {len(unique):,} (after {n_dupes} dupes removed)")
    print(f"  train.jsonl:     {n_train:,} ({TRAIN_RATIO*100:.0f}%)")
    print(f"  val.jsonl:       {n_val:,} ({VAL_RATIO*100:.0f}%)")
    print(f"  holdout.jsonl:   {n_holdout:,} ({HOLDOUT_RATIO*100:.0f}%)")
    print(f"  combined.jsonl:  {len(unique):,}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
