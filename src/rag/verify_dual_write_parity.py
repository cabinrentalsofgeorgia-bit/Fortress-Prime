#!/usr/bin/env python3
"""
verify_dual_write_parity.py — Phase 5a operational parity check.

Compares fgp_knowledge (spark-2) against fgp_vrs_knowledge (spark-4):
  - Point count parity
  - Optional vector spot-check on a random sample
  - Optional search comparison (--compare-search) for pre-cutover gate

Usage:
  python3 -m src.rag.verify_dual_write_parity [--sample N] [--compare-search QUERY]

  --sample N             Spot-check N random vectors byte-for-byte (default: 0 = skip)
  --compare-search QUERY Run the same search against both endpoints and compare top-5
                         results. Reports hit-rate agreement. Run before flipping
                         READ_FROM_VRS_STORE=true.
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


EMBED_URL   = "http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM   = 768


def _embed(query: str) -> list[float]:
    """Embed a query string via the local NIM endpoint (sync)."""
    import urllib.request, json as _json  # noqa: E401
    payload = _json.dumps({"model": EMBED_MODEL, "prompt": query[:8000]}).encode()
    req = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = _json.loads(resp.read())
    vec = data.get("embedding", [])
    if len(vec) != EMBED_DIM:
        raise ValueError(f"Expected {EMBED_DIM}-dim vector, got {len(vec)}")
    return vec


def _qdrant_search(url: str, collection: str, vec: list[float], top_k: int = 5) -> list[dict]:
    """Run a top-k search against a Qdrant collection (sync, no SDK)."""
    import urllib.request, json as _json  # noqa: E401
    body = _json.dumps({
        "vector": vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }).encode()
    req = urllib.request.Request(
        f"{url}/collections/{collection}/points/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return _json.loads(resp.read()).get("result", [])


def compare_search(query: str, top_k: int = 5) -> int:
    """Run the same query on both endpoints and report agreement.

    Agreement is measured as the fraction of spark-4's top-k results whose
    record_id appears anywhere in spark-2's top-k results.  ≥95% required
    before flipping READ_FROM_VRS_STORE=true.

    Returns 0 (PASS) or 1 (FAIL / agreement below threshold).
    """
    log.info("compare_search: query=%r top_k=%d", query[:80], top_k)

    try:
        vec = _embed(query)
        log.info("embedding_ok dim=%d", len(vec))
    except Exception as exc:
        log.error("embedding_failed: %s", exc)
        return 1

    try:
        src_hits = _qdrant_search(SOURCE_URL, SOURCE_COLLECTION, vec, top_k)
        log.info("source_hits=%d from %s/%s", len(src_hits), SOURCE_URL, SOURCE_COLLECTION)
    except Exception as exc:
        log.error("source_search_failed: %s", exc)
        return 1

    try:
        tgt_hits = _qdrant_search(TARGET_URL, TARGET_COLLECTION, vec, top_k)
        log.info("target_hits=%d from %s/%s", len(tgt_hits), TARGET_URL, TARGET_COLLECTION)
    except Exception as exc:
        log.error("target_search_failed: %s", exc)
        return 1

    if not src_hits:
        log.warning("source returned 0 results — no agreement to measure")
        return 1

    # Report top results from each side
    for rank, hit in enumerate(src_hits[:top_k], 1):
        payload = hit.get("payload", {})
        log.info(
            "source rank=%d score=%.4f record_id=%s text_preview=%r",
            rank, hit.get("score", 0), payload.get("record_id", "")[:12],
            (payload.get("text") or "")[:80],
        )
    for rank, hit in enumerate(tgt_hits[:top_k], 1):
        payload = hit.get("payload", {})
        log.info(
            "target rank=%d score=%.4f record_id=%s text_preview=%r",
            rank, hit.get("score", 0), payload.get("record_id", "")[:12],
            (payload.get("text") or "")[:80],
        )

    # Agreement: fraction of target top-k whose record_id is in source top-k
    src_ids = {
        hit.get("payload", {}).get("record_id", "") for hit in src_hits[:top_k]
    }
    matches = sum(
        1 for h in tgt_hits[:top_k]
        if h.get("payload", {}).get("record_id", "") in src_ids
    )
    agreement = matches / max(len(tgt_hits), 1)
    log.info(
        "search_agreement: matches=%d/%d agreement=%.1f%%",
        matches, len(tgt_hits[:top_k]), agreement * 100,
    )

    threshold = 0.95
    if agreement >= threshold:
        log.info("compare_search_result: PASS (>=%.0f%% agreement)", threshold * 100)
        return 0
    else:
        log.warning(
            "compare_search_result: FAIL (%.1f%% < %.0f%% required)",
            agreement * 100, threshold * 100,
        )
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRS Qdrant parity check")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="Spot-check N random vectors (default: 0 = count only)")
    parser.add_argument("--compare-search", metavar="QUERY", default=None,
                        help="Run same query on both endpoints and report top-5 agreement. "
                             "Use before flipping READ_FROM_VRS_STORE=true.")
    args = parser.parse_args()

    if args.compare_search:
        sys.exit(compare_search(args.compare_search))
    else:
        sys.exit(check_parity(args.sample))
