#!/usr/bin/env python3
"""
verify_dual_write_parity.py — Phase 5a operational parity check.

Compares fgp_knowledge (spark-2) against fgp_vrs_knowledge (spark-4):
  - Point count parity
  - Optional vector spot-check on a random sample

Usage:
  python3 -m src.rag.verify_dual_write_parity [--sample N]

  --sample N   Spot-check N random vectors byte-for-byte (default: 0 = skip)
"""
from __future__ import annotations

import argparse
import logging
import random
import sys

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"parity_check"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("parity_check")

SOURCE_URL        = "http://192.168.0.100:6333"
SOURCE_COLLECTION = "fgp_knowledge"
TARGET_URL        = "http://192.168.0.106:6333"
TARGET_COLLECTION = "fgp_vrs_knowledge"


def _client(url: str):
    from qdrant_client import QdrantClient
    return QdrantClient(url=url, timeout=15, check_compatibility=False)


def _count(client, collection: str) -> int:
    return client.get_collection(collection).points_count


def check_parity(sample_n: int) -> int:
    source = _client(SOURCE_URL)
    target = _client(TARGET_URL)

    src_count = _count(source, SOURCE_COLLECTION)
    tgt_count = _count(target, TARGET_COLLECTION)

    parity_pct = (tgt_count / src_count * 100) if src_count else 0.0
    log.info(
        "count_check: source=%d target=%d parity=%.1f%%",
        src_count, tgt_count, parity_pct,
    )

    if src_count != tgt_count:
        log.warning(
            "COUNT MISMATCH: source=%d target=%d delta=%d",
            src_count, tgt_count, src_count - tgt_count,
        )

    if sample_n <= 0 or src_count == 0:
        status = "PASS" if src_count == tgt_count else "FAIL"
        log.info("parity_result: %s (count only)", status)
        return 0 if src_count == tgt_count else 1

    # Vector spot-check
    sample_pts, _ = source.scroll(
        SOURCE_COLLECTION,
        limit=max(sample_n * 3, 50),
        with_vectors=True,
        with_payload=False,
    )
    sample = random.sample(sample_pts, min(sample_n, len(sample_pts)))
    ids = [str(p.id) for p in sample]
    src_vecs = {str(p.id): p.vector for p in sample}

    tgt_pts = target.retrieve(
        TARGET_COLLECTION,
        ids=ids,
        with_vectors=True,
        with_payload=False,
    )
    tgt_vecs = {str(p.id): p.vector for p in tgt_pts}

    mismatches = 0
    missing = 0
    for pid, sv in src_vecs.items():
        tv = tgt_vecs.get(pid)
        if tv is None:
            log.warning("MISSING on target: %s", pid[:8])
            missing += 1
        elif sv != tv:
            log.warning("VECTOR MISMATCH: %s", pid[:8])
            mismatches += 1

    log.info(
        "vector_check: sampled=%d missing=%d mismatches=%d",
        len(src_vecs), missing, mismatches,
    )

    ok = (src_count == tgt_count) and missing == 0 and mismatches == 0
    log.info("parity_result: %s", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRS Qdrant parity check")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="Spot-check N random vectors (default: 0 = count only)")
    args = parser.parse_args()
    sys.exit(check_parity(args.sample))
