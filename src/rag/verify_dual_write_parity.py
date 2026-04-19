#!/usr/bin/env python3
"""
verify_dual_write_parity.py — Phase 5a operational parity check.

Compares fgp_knowledge (spark-2) against fgp_vrs_knowledge (spark-4):
  - Point count parity
  - Optional vector spot-check on a random sample
  - Optional search comparison (--compare-search) for pre-cutover gate
  - --monitor mode: hourly soak monitoring with structured JSON output

Usage:
  python3 -m src.rag.verify_dual_write_parity [--sample N] [--compare-search QUERY]
  python3 -m src.rag.verify_dual_write_parity --monitor

  --sample N             Spot-check N random vectors byte-for-byte (default: 0 = skip)
  --compare-search QUERY Run the same search against both endpoints and compare top-5
                         results. Reports hit-rate agreement. Run before flipping
                         READ_FROM_VRS_STORE=true.
  --monitor              Non-interactive soak mode. Runs a fixed set of queries,
                         writes a JSON result line to PARITY_LOG, writes an alarm
                         file to PARITY_ALARM_DIR on hard fail.
                         Exit codes: 0=PASS, 1=SOFT_FAIL (90-95% or rank swaps),
                         2=HARD_FAIL (<90%, count mismatch, or connection error).

Exit codes in --monitor mode:
  0  PASS      — count match + all search agreements ≥95%
  1  SOFT_FAIL — all connections ok, parity 90-95% (rank-swap noise)
  2  HARD_FAIL — count mismatch, connection error, or parity <90%
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

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


# Ollama embedding endpoint (nomic-embed-text, 768-dim).
# Port 80 Nginx proxy is unavailable from this host; use Ollama directly at :11434.
EMBED_URL   = os.getenv("PARITY_EMBED_URL", "http://192.168.0.100:11434/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM   = 768

# Monitor mode config
PARITY_LOG       = Path(os.getenv("PARITY_LOG",       "/var/log/fortress-parity.log"))
_PARITY_LOG_FALLBACK = Path.home() / "fortress-parity.log"
PARITY_ALARM_DIR = Path(os.getenv("PARITY_ALARM_DIR", "/mnt/fortress_nas/parity-alarm"))
PARITY_LOG_MAX_LINES = int(os.getenv("PARITY_LOG_MAX_LINES", "200"))

_MONITOR_QUERIES: list[str] = [
    "Fallen Timber Lodge",
    "pricing weekend stay",
    "deck exterior materials",
    "booking policy",
    "amenities WiFi",
]


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


def _parity_log_append(line: str) -> None:
    """Append a line to the parity log, with size-based rotation (keep last N lines)."""
    target = PARITY_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Read existing, keep last N-1 lines, append new
        existing: list[str] = []
        if target.exists():
            existing = target.read_text(encoding="utf-8").splitlines()
        existing = existing[-(PARITY_LOG_MAX_LINES - 1):]
        existing.append(line)
        target.write_text("\n".join(existing) + "\n", encoding="utf-8")
    except OSError:
        try:
            _PARITY_LOG_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            with open(_PARITY_LOG_FALLBACK, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            log.warning("parity_log_write_failed cannot write to %s or %s", PARITY_LOG, _PARITY_LOG_FALLBACK)


def _write_alarm(ts: str, reason: str, detail: dict) -> None:
    """Write an alarm file to PARITY_ALARM_DIR for pickup by drift_alarm."""
    try:
        PARITY_ALARM_DIR.mkdir(parents=True, exist_ok=True)
        safe_ts = ts.replace(":", "").replace("-", "")
        alarm_path = PARITY_ALARM_DIR / f"alarm-{safe_ts}.error"
        payload = json.dumps({"timestamp": ts, "reason": reason, **detail}, indent=2)
        alarm_path.write_text(payload + "\n", encoding="utf-8")
        log.error("parity_alarm_written path=%s", alarm_path)
    except OSError as exc:
        log.error("parity_alarm_write_failed error=%s", exc)


def _search_agreement(query: str, top_k: int = 5) -> tuple[float, str]:
    """Return (agreement_fraction, status_label) for a single query.

    status_label: 'pass' | 'soft_fail' | 'hard_fail' | 'error'
    """
    try:
        vec = _embed(query)
    except Exception as exc:
        log.error("embed_failed query=%r error=%s", query[:50], exc)
        return 0.0, "error"

    try:
        src_hits = _qdrant_search(SOURCE_URL, SOURCE_COLLECTION, vec, top_k)
        tgt_hits = _qdrant_search(TARGET_URL, TARGET_COLLECTION, vec, top_k)
    except Exception as exc:
        log.error("search_failed query=%r error=%s", query[:50], exc)
        return 0.0, "error"

    if not src_hits or not tgt_hits:
        return 0.0, "hard_fail"

    src_ids = {h.get("payload", {}).get("record_id", "") for h in src_hits[:top_k]}
    matches = sum(1 for h in tgt_hits[:top_k] if h.get("payload", {}).get("record_id", "") in src_ids)
    agreement = matches / max(len(tgt_hits[:top_k]), 1)

    if agreement >= 0.95:
        status = "pass"
    elif agreement >= 0.90:
        status = "soft_fail"
    else:
        status = "hard_fail"

    return agreement, status


def run_monitor() -> int:
    """Non-interactive soak mode. Returns 0/1/2 exit code."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info("monitor_start ts=%s queries=%d", ts, len(_MONITOR_QUERIES))

    # --- Count parity ---
    try:
        source = _client(SOURCE_URL)
        target = _client(TARGET_URL)
        src_count = _count(source, SOURCE_COLLECTION)
        tgt_count = _count(target, TARGET_COLLECTION)
        count_match = src_count == tgt_count
        count_parity_pct = (tgt_count / src_count * 100) if src_count else 0.0
    except Exception as exc:
        log.error("count_check_failed error=%s", exc)
        result = {
            "timestamp": ts, "overall_status": "hard_fail",
            "reason": "connection_error", "error": str(exc)[:200],
        }
        _parity_log_append(json.dumps(result))
        _write_alarm(ts, "connection_error", {"error": str(exc)[:200]})
        return 2

    log.info("count_check src=%d tgt=%d parity=%.1f%%", src_count, tgt_count, count_parity_pct)

    if not count_match:
        log.error("COUNT MISMATCH src=%d tgt=%d delta=%d", src_count, tgt_count, src_count - tgt_count)

    # --- Search parity ---
    per_query: dict[str, dict] = {}
    for q in _MONITOR_QUERIES:
        agreement, status = _search_agreement(q)
        per_query[q] = {"agreement": round(agreement, 4), "status": status}
        log.info("query_result query=%r agreement=%.1f%% status=%s", q[:50], agreement * 100, status)

    # --- Overall status ---
    statuses = [v["status"] for v in per_query.values()]
    has_error    = "error"     in statuses
    has_hard     = "hard_fail" in statuses
    has_soft     = "soft_fail" in statuses

    if not count_match or has_error or has_hard:
        overall = "hard_fail"
        exit_code = 2
    elif has_soft:
        overall = "soft_fail"
        exit_code = 1
    else:
        overall = "pass"
        exit_code = 0

    result = {
        "timestamp":         ts,
        "overall_status":    overall,
        "count_parity_pct":  round(count_parity_pct, 1),
        "src_count":         src_count,
        "tgt_count":         tgt_count,
        "count_match":       count_match,
        "search_parity":     per_query,
    }
    log.info("monitor_result overall=%s exit=%d", overall, exit_code)
    _parity_log_append(json.dumps(result))

    if exit_code == 2:
        _write_alarm(ts, overall, {
            "count_match": count_match,
            "src_count": src_count,
            "tgt_count": tgt_count,
            "failed_queries": {q: v for q, v in per_query.items() if v["status"] != "pass"},
        })
    elif exit_code == 1:
        log.warning("SOFT_FAIL soft queries=%s", [q for q, v in per_query.items() if v["status"] == "soft_fail"])

    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRS Qdrant parity check")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="Spot-check N random vectors (default: 0 = count only)")
    parser.add_argument("--compare-search", metavar="QUERY", default=None,
                        help="Run same query on both endpoints and report top-5 agreement. "
                             "Use before flipping READ_FROM_VRS_STORE=true.")
    parser.add_argument("--monitor", action="store_true",
                        help="Hourly soak mode: runs fixed query set, writes JSON to PARITY_LOG, "
                             "alarm file on hard fail. Exit 0=pass, 1=soft_fail, 2=hard_fail.")
    args = parser.parse_args()

    if args.monitor:
        sys.exit(run_monitor())
    elif args.compare_search:
        sys.exit(compare_search(args.compare_search))
    else:
        sys.exit(check_parity(args.sample))
