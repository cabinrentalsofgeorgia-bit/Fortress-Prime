#!/usr/bin/env python3
"""
FORTRESS PRIME — Vector Healing Script
=======================================
Three-pass healer for Qdrant collections with missing/broken vectors or junk payloads.

  Pass 1 (Audit):    Read-only scan, classify every point as healthy/missing_vector/junk/orphan
  Pass 2 (Re-embed):  Generate missing vectors using nomic-embed-text and upsert (payload preserved)
  Pass 3 (Purge):     Delete junk payloads (opt-in only via --purge-junk flag)

Safety:
  - Never deletes or modifies text payloads during re-embed
  - Junk purge requires explicit --purge-junk flag
  - --dry-run flag audits without writing anything
  - Progress logged per-point; resumable on re-run

Usage:
  python3 src/heal_vectors.py                                   # audit + heal both collections
  python3 src/heal_vectors.py --collection black_swan_intel      # heal one collection
  python3 src/heal_vectors.py --dry-run                          # audit only
  python3 src/heal_vectors.py --purge-junk                       # also delete junk payloads
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("heal_vectors")

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

QDRANT_HEADERS: dict[str, str] = {"Content-Type": "application/json"}
if QDRANT_API_KEY:
    QDRANT_HEADERS["api-key"] = QDRANT_API_KEY

DEFAULT_COLLECTIONS = ["black_swan_intel", "real_estate_intel"]
PAGE_SIZE = 50
EXPECTED_DIMS = 768

AUDIT_LOG_DIR = Path("/mnt/fortress_nas/fortress_data/ai_brain/logs/vector_healing")

_JUNK_PATTERNS = [
    re.compile(r"^\s*[\{\[]", re.DOTALL),
    re.compile(r"(import |from .+ import |def |class |sudo |docker |chmod |mkdir )", re.IGNORECASE),
    re.compile(r"(BEGIN|COMMIT|CREATE TABLE|ALTER TABLE|INSERT INTO)", re.IGNORECASE),
    re.compile(r"^[\s\-\|\#\=\>\<\`]{20,}$", re.MULTILINE),
    re.compile(r"\b(ssh-|PRIVATE KEY|api_key=|password=|secret=)", re.IGNORECASE),
]


def _is_junk(text: str) -> bool:
    if not text or len(text.strip()) < 50:
        return True
    for pat in _JUNK_PATTERNS:
        if pat.search(text[:500]):
            return True
    return False


def _embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning(f"Embedding endpoint returned {resp.status_code}")
            return None
        emb = resp.json().get("embedding")
        if emb and len(emb) == EXPECTED_DIMS:
            return emb
        log.warning(f"Unexpected embedding dims: {len(emb) if emb else 0}")
        return None
    except requests.RequestException as exc:
        log.warning(f"Embedding request failed: {exc}")
        return None


def _scroll_all(collection: str) -> list[dict]:
    """Paginate through entire collection, returning all points with vectors and payloads."""
    all_points = []
    offset = None

    while True:
        body: dict = {
            "limit": PAGE_SIZE,
            "with_payload": True,
            "with_vector": True,
        }
        if offset is not None:
            body["offset"] = offset

        try:
            resp = requests.post(
                f"{QDRANT_URL}/collections/{collection}/points/scroll",
                headers=QDRANT_HEADERS,
                json=body,
                timeout=30,
            )
            if resp.status_code != 200:
                log.error(f"Scroll failed for {collection}: {resp.status_code}")
                break

            data = resp.json().get("result", {})
            points = data.get("points", [])
            next_offset = data.get("next_page_offset")

            all_points.extend(points)

            if not next_offset or not points:
                break
            offset = next_offset

        except requests.RequestException as exc:
            log.error(f"Scroll request failed: {exc}")
            break

    return all_points


def _classify_point(point: dict) -> str:
    text = point.get("payload", {}).get("text", "")
    vector = point.get("vector")
    has_vector = bool(vector) and len(vector) == EXPECTED_DIMS
    has_text = bool(text and len(text.strip()) >= 10)

    if not has_text and not has_vector:
        return "orphan"
    if has_text and _is_junk(text):
        return "junk_payload"
    if has_text and not has_vector:
        return "missing_vector"
    return "healthy"


def _upsert_point(collection: str, point_id: str, vector: list[float], payload: dict) -> bool:
    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{collection}/points",
            headers=QDRANT_HEADERS,
            json={
                "points": [{
                    "id": point_id,
                    "vector": vector,
                    "payload": payload,
                }]
            },
            timeout=30,
        )
        return resp.status_code == 200
    except requests.RequestException as exc:
        log.warning(f"Upsert failed for {point_id}: {exc}")
        return False


def _delete_points(collection: str, point_ids: list[str]) -> bool:
    if not point_ids:
        return True
    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/delete",
            headers=QDRANT_HEADERS,
            json={"points": point_ids},
            timeout=30,
        )
        return resp.status_code == 200
    except requests.RequestException as exc:
        log.warning(f"Delete failed: {exc}")
        return False


def heal_collection(
    collection: str,
    dry_run: bool = False,
    purge_junk: bool = False,
) -> dict[str, int]:
    """
    Three-pass healing for a single Qdrant collection.

    Returns dict with counts: healthy, missing_vector, junk_payload, orphan,
                              healed, heal_failed, purged
    """
    log.info(f"{'[DRY RUN] ' if dry_run else ''}Healing collection: {collection}")

    points = _scroll_all(collection)
    total = len(points)
    log.info(f"Scrolled {total} points from {collection}")

    stats = {
        "total": total,
        "healthy": 0,
        "missing_vector": 0,
        "junk_payload": 0,
        "orphan": 0,
        "healed": 0,
        "heal_failed": 0,
        "purged": 0,
    }

    classified: dict[str, list[dict]] = {
        "healthy": [],
        "missing_vector": [],
        "junk_payload": [],
        "orphan": [],
    }

    # --- Pass 1: Audit ---
    log.info("Pass 1: Auditing points...")
    for i, point in enumerate(points):
        category = _classify_point(point)
        stats[category] += 1
        classified[category].append(point)
        if (i + 1) % 50 == 0:
            log.info(f"  [{i + 1}/{total}] Audited...")

    log.info(
        f"Audit complete: {stats['healthy']} healthy, {stats['missing_vector']} missing_vector, "
        f"{stats['junk_payload']} junk, {stats['orphan']} orphan"
    )

    # --- Write audit CSV ---
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_path = AUDIT_LOG_DIR / f"audit_{collection}_{ts}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["point_id", "category", "text_length", "has_vector", "text_preview"])
            for cat, cat_points in classified.items():
                for p in cat_points:
                    text = p.get("payload", {}).get("text", "")
                    vec = p.get("vector")
                    writer.writerow([
                        p.get("id", ""),
                        cat,
                        len(text),
                        bool(vec) and len(vec) == EXPECTED_DIMS,
                        text[:100].replace("\n", " "),
                    ])
        log.info(f"Audit CSV written: {csv_path}")
    except Exception as exc:
        log.warning(f"Could not write audit CSV: {exc}")

    if dry_run:
        log.info("[DRY RUN] Skipping Pass 2 and Pass 3")
        return stats

    # --- Pass 2: Re-embed missing vectors ---
    missing = classified["missing_vector"]
    if missing:
        log.info(f"Pass 2: Re-embedding {len(missing)} points with missing vectors...")
        for i, point in enumerate(missing):
            pid = point.get("id")
            text = point.get("payload", {}).get("text", "")
            payload = point.get("payload", {})

            log.info(f"  [{i + 1}/{len(missing)}] Healing {collection}: {pid}")
            vector = _embed(text)
            if vector:
                if _upsert_point(collection, pid, vector, payload):
                    stats["healed"] += 1
                else:
                    stats["heal_failed"] += 1
            else:
                stats["heal_failed"] += 1
                log.warning(f"  Skipped {pid} — embedding failed")
    else:
        log.info("Pass 2: No missing vectors to heal")

    # --- Pass 3: Purge junk (opt-in) ---
    junk = classified["junk_payload"]
    orphans = classified["orphan"]
    if purge_junk and (junk or orphans):
        purge_ids = [p.get("id") for p in junk + orphans if p.get("id")]
        log.info(f"Pass 3: Purging {len(purge_ids)} junk/orphan points...")
        if _delete_points(collection, purge_ids):
            stats["purged"] = len(purge_ids)
            log.info(f"  Purged {len(purge_ids)} points")
        else:
            log.warning("  Purge failed")
    elif junk or orphans:
        log.info(
            f"Pass 3: {len(junk)} junk + {len(orphans)} orphan points found "
            f"but --purge-junk not set (skipping)"
        )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Heal Qdrant collections with missing vectors")
    parser.add_argument("--collection", type=str, help="Heal specific collection (default: both)")
    parser.add_argument("--dry-run", action="store_true", help="Audit only, no writes")
    parser.add_argument("--purge-junk", action="store_true", help="Also delete junk/orphan points")
    args = parser.parse_args()

    collections = [args.collection] if args.collection else DEFAULT_COLLECTIONS

    log.info("Vector Healing Script starting")
    log.info(f"Collections: {collections}")
    log.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}{' + PURGE JUNK' if args.purge_junk else ''}")
    log.info(f"Qdrant: {QDRANT_URL}")
    log.info(f"Embed: {EMBED_URL} ({EMBED_MODEL})")

    all_stats = {}
    for coll in collections:
        stats = heal_collection(coll, dry_run=args.dry_run, purge_junk=args.purge_junk)
        all_stats[coll] = stats

    log.info("")
    log.info("=" * 60)
    log.info("HEALING SUMMARY")
    log.info("=" * 60)
    for coll, stats in all_stats.items():
        log.info(f"  {coll}:")
        log.info(f"    total={stats['total']} healthy={stats['healthy']} "
                 f"missing={stats['missing_vector']} junk={stats['junk_payload']} "
                 f"orphan={stats['orphan']}")
        if not args.dry_run:
            log.info(f"    healed={stats['healed']} heal_failed={stats['heal_failed']} "
                     f"purged={stats['purged']}")


if __name__ == "__main__":
    main()
