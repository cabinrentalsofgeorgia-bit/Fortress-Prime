#!/usr/bin/env python3
"""
training_pairs_sample.py — Print N random training pairs for quality review.

Usage:
  python -m src.legal.training_pairs_sample [N] [--source combined|train|scripted|godhead]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

CORPUS_ROOT = Path(os.getenv("LEGAL_CORPUS_ROOT", "/mnt/fortress_nas/legal-corpus"))
PAIRS_DIR = CORPUS_ROOT / "training-pairs"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.legal.training_pairs_sample",
        description="Print random training pairs for quality review",
    )
    parser.add_argument("n", type=int, nargs="?", default=20, help="Number of pairs to show")
    parser.add_argument("--source", default="combined",
                        choices=["combined", "train", "val", "holdout", "scripted", "godhead"],
                        help="Which JSONL file to sample from")
    parser.add_argument("--pattern", choices=["A", "B", "C", "D", "E"],
                        help="Filter by pattern (optional)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    path = PAIRS_DIR / f"{args.source}.jsonl"
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        print("Run: python -m src.legal.training_pairs_scripted", file=sys.stderr)
        return 1

    pairs = [json.loads(l) for l in path.open() if l.strip()]
    if args.pattern:
        pairs = [p for p in pairs if p.get("pattern") == args.pattern]

    rng = random.Random(args.seed)
    sample = rng.sample(pairs, min(args.n, len(pairs)))

    print(f"\n{'='*70}")
    print(f"Sampling {len(sample)} pairs from {path.name} (total: {len(pairs):,})")
    if args.pattern:
        print(f"Filtered to Pattern {args.pattern}")
    print(f"{'='*70}\n")

    for i, p in enumerate(sample, 1):
        pattern = p.get("pattern", "?")
        case = p.get("metadata", {}).get("case", "unknown")
        print(f"[{i}/{len(sample)}] Pattern {pattern} — {case[:60]}")
        print(f"{'─'*60}")
        print(f"INSTRUCTION:\n{p.get('instruction', '')}\n")
        print(f"OUTPUT:\n{p.get('output', '')}")
        print(f"\n{'─'*60}\n")

    # Summary stats
    from collections import Counter
    pat_counts = Counter(p.get("pattern", "?") for p in pairs)
    print("\nPattern distribution in this file:")
    for pat in sorted(pat_counts):
        print(f"  Pattern {pat}: {pat_counts[pat]:,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
