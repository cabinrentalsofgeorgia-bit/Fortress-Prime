#!/usr/bin/env python3
"""
migrate_fgp_to_vrs.py — Phase 5a Part 2 snapshot copy.

Copies all points from spark-2 fgp_knowledge (source of truth, read-only)
to spark-4 fgp_vrs_knowledge (new VRS vector store).

  - Preserves point IDs, vectors, and all payload fields.
  - Uses scroll + upsert (idempotent — safe to re-run).
  - Refuses to write if target is non-empty unless --force is given.
  - Post-migration: verifies count parity and spot-checks 10 random vectors
    byte-for-byte between source and target.

spark-2 fgp_knowledge remains the active read path until Phase 5a Part 3.

Usage:
  python3 -m src.rag.migrate_fgp_to_vrs [--dry-run] [--batch-size N] [--force]
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"migrate_fgp"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("migrate_fgp")

SOURCE_URL        = "http://192.168.0.100:6333"
SOURCE_COLLECTION = "fgp_knowledge"
TARGET_URL        = "http://192.168.0.106:6333"
TARGET_COLLECTION = "fgp_vrs_knowledge"
EXPECTED_DIM      = 768
EXPECTED_DISTANCE = "Cosine"
VERIFY_SAMPLE_N   = 10


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def _make_client(url: str):
    from qdrant_client import QdrantClient
    return QdrantClient(url=url, timeout=60, check_compatibility=False)


def _collection_info(client, collection: str) -> tuple[int, int, str]:
    """Return (points_count, vector_size, distance)."""
    info = client.get_collection(collection)
    p = info.config.params
    return (
        info.points_count,
        p.vectors.size,
        p.vectors.distance.name,  # "Cosine" | "Euclid" | "Dot"
    )


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def _verify_schemas(source, target) -> tuple[int, int]:
    """
    Verify vector dimensions and distance match on both ends.
    Returns (src_count, tgt_count).
    Raises ValueError on mismatch.
    """
    src_count, src_dim, src_dist = _collection_info(source, SOURCE_COLLECTION)
    tgt_count, tgt_dim, tgt_dist = _collection_info(target, TARGET_COLLECTION)

    if src_dim != EXPECTED_DIM:
        raise ValueError(
            f"Source dimension mismatch: expected {EXPECTED_DIM}, got {src_dim}"
        )
    if tgt_dim != EXPECTED_DIM:
        raise ValueError(
            f"Target dimension mismatch: expected {EXPECTED_DIM}, got {tgt_dim}"
        )
    if src_dist.lower() != EXPECTED_DISTANCE.lower():
        raise ValueError(
            f"Source distance mismatch: expected {EXPECTED_DISTANCE}, got {src_dist}"
        )
    if tgt_dist.lower() != EXPECTED_DISTANCE.lower():
        raise ValueError(
            f"Target distance mismatch: expected {EXPECTED_DISTANCE}, got {tgt_dist}"
        )
    if src_count == 0:
        raise ValueError("Source collection is empty — nothing to migrate")

    return src_count, tgt_count


# ---------------------------------------------------------------------------
# Core migration
# ---------------------------------------------------------------------------

def _scroll_all(source, batch_size: int) -> list:
    """Scroll all points from source, return as list of PointStruct."""
    from qdrant_client.models import PointStruct

    points: list[PointStruct] = []
    offset = None
    while True:
        batch, next_offset = source.scroll(
            SOURCE_COLLECTION,
            offset=offset,
            limit=batch_size,
            with_vectors=True,
            with_payload=True,
        )
        if not batch:
            break
        points.extend(
            PointStruct(id=p.id, vector=p.vector, payload=p.payload)
            for p in batch
        )
        log.info(
            "scrolled batch total=%d latest_offset=%s",
            len(points),
            str(batch[-1].id)[:8],
        )
        if next_offset is None:
            break
        offset = next_offset
    return points


def _upsert_batched(target, points: list, batch_size: int) -> int:
    """Upsert all points to target in batches. Returns total upserted."""
    total = 0
    for i in range(0, len(points), batch_size):
        chunk = points[i : i + batch_size]
        target.upsert(collection_name=TARGET_COLLECTION, points=chunk, wait=True)
        total += len(chunk)
        log.info("upserted %d/%d", total, len(points))
    return total


# ---------------------------------------------------------------------------
# Post-migration verification
# ---------------------------------------------------------------------------

def _verify(source, target, src_count: int, tgt_count: int) -> bool:
    """
    Two-phase verification:
    1. Count parity: source count == target count.
    2. Vector spot-check: 10 random point IDs — vectors must be byte-identical.
    Returns True if all checks pass.
    """
    ok = True

    if tgt_count != src_count:
        log.error(
            "COUNT MISMATCH: source=%d target=%d — migration incomplete",
            src_count, tgt_count,
        )
        ok = False
    else:
        log.info("count_check PASS: source=%d target=%d", src_count, tgt_count)

    # Sample 10 random IDs from source
    sample_batch, _ = source.scroll(
        SOURCE_COLLECTION,
        limit=max(src_count, VERIFY_SAMPLE_N * 3),
        with_vectors=True,
        with_payload=False,
    )
    sample_points = random.sample(sample_batch, min(VERIFY_SAMPLE_N, len(sample_batch)))
    sample_ids = [str(p.id) for p in sample_points]
    src_vectors = {str(p.id): p.vector for p in sample_points}

    tgt_results = target.retrieve(
        TARGET_COLLECTION,
        ids=sample_ids,
        with_vectors=True,
        with_payload=False,
    )
    tgt_vectors = {str(p.id): p.vector for p in tgt_results}

    mismatches = 0
    for pid, src_vec in src_vectors.items():
        tgt_vec = tgt_vectors.get(pid)
        if tgt_vec is None:
            log.error("VECTOR_CHECK FAIL: point %s not found on target", pid[:8])
            mismatches += 1
        elif src_vec != tgt_vec:
            log.error("VECTOR_CHECK FAIL: point %s vector mismatch", pid[:8])
            mismatches += 1

    if mismatches:
        log.error("vector_check FAIL: %d/%d mismatches", mismatches, len(src_vectors))
        ok = False
    else:
        log.info(
            "vector_check PASS: %d/%d sampled points match byte-for-byte",
            len(src_vectors), len(src_vectors),
        )

    return ok


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(dry_run: bool, batch_size: int, force: bool) -> int:
    t_start = datetime.now(tz=timezone.utc)
    log.info(
        "=== Phase 5a Part 2: fgp_knowledge → fgp_vrs_knowledge ==="
    )
    log.info(
        "source=%s/%s  target=%s/%s  dry_run=%s  batch_size=%d  force=%s",
        SOURCE_URL, SOURCE_COLLECTION,
        TARGET_URL, TARGET_COLLECTION,
        dry_run, batch_size, force,
    )

    source = _make_client(SOURCE_URL)
    target = _make_client(TARGET_URL)

    # Schema + count check
    try:
        src_count, tgt_count = _verify_schemas(source, target)
    except ValueError as e:
        log.error("pre_check_failed: %s", e)
        return 1

    log.info(
        "pre_check PASS: source=%d points  target=%d points  dim=%d  dist=%s",
        src_count, tgt_count, EXPECTED_DIM, EXPECTED_DISTANCE,
    )

    if dry_run:
        log.info(
            "[DRY RUN] Would migrate %d points from %s → %s. No writes performed.",
            src_count, SOURCE_COLLECTION, TARGET_COLLECTION,
        )
        return 0

    # Non-empty target safety check
    if tgt_count > 0 and not force:
        log.error(
            "target already has %d points — use --force to overwrite. "
            "Migration is idempotent via upsert.",
            tgt_count,
        )
        return 1
    if tgt_count > 0:
        log.warning(
            "target has %d existing points — --force set, proceeding with upsert",
            tgt_count,
        )

    # Scroll all from source
    log.info("scrolling all points from source …")
    points = _scroll_all(source, batch_size)
    log.info("scroll complete: %d points fetched", len(points))

    if len(points) != src_count:
        log.error(
            "scroll count mismatch: fetched %d but source reports %d",
            len(points), src_count,
        )
        return 1

    # Upsert to target
    log.info("upserting to target …")
    upserted = _upsert_batched(target, points, batch_size)

    t_end = datetime.now(tz=timezone.utc)
    elapsed = (t_end - t_start).total_seconds()

    # Post-migration verification
    log.info("running post-migration verification …")
    final_tgt_count, _, _ = _collection_info(target, TARGET_COLLECTION)
    passed = _verify(source, target, src_count, final_tgt_count)

    log.info(
        "=== migration complete: upserted=%d elapsed=%.1fs verified=%s ===",
        upserted, elapsed, "PASS" if passed else "FAIL",
    )

    return 0 if passed else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Phase 5a Part 2: migrate fgp_knowledge → fgp_vrs_knowledge"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Verify connectivity and counts without writing",
    )
    parser.add_argument(
        "--batch-size", type=int, default=64, metavar="N",
        help="Points per scroll/upsert batch (default: 64)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Proceed even if target is non-empty (upsert is idempotent)",
    )
    args = parser.parse_args()
    sys.exit(run(args.dry_run, args.batch_size, args.force))
