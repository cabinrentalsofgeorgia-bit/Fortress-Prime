#!/usr/bin/env python3
"""
FORTRESS PRIME — Real Estate Data Ingestion (Real Estate Mogul Persona)
=======================================================================
Populates the real_estate_intel Qdrant collection with:
  1. FRED housing/construction macro series (HOUST, WPU0811, MORTGAGE30US, MSPUS, PERMIT)
  2. Local CSV/JSON reports from the NAS Drop Zone

Drop Zone: /mnt/fortress_nas/Intelligence/Real_Estate/raw_data/
  - Place .csv or .json files here; the script picks them up on the next run
  - Files are NOT deleted after ingestion; deduplication prevents re-processing

Cron: 15 4 * * * (daily, after macro ingestion at 04:00)

Run:  python3 src/ingest_real_estate_data.py
      python3 src/ingest_real_estate_data.py --fred-only
      python3 src/ingest_real_estate_data.py --local-only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_real_estate")

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

QDRANT_HEADERS: dict[str, str] = {}
if QDRANT_API_KEY:
    QDRANT_HEADERS["api-key"] = QDRANT_API_KEY

COLLECTION = "real_estate_intel"
DROP_ZONE = Path(os.getenv(
    "RE_DROP_ZONE",
    "/mnt/fortress_nas/Intelligence/Real_Estate/raw_data",
))
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100

FRED_RE_SERIES = {
    "HOUST": "Housing Starts (thousands of units)",
    "WPU0811": "PPI: Lumber & Wood Products",
    "MORTGAGE30US": "30-Year Fixed Mortgage Rate",
    "MSPUS": "Median Sales Price of Houses Sold (USD)",
    "PERMIT": "New Private Housing Units Authorized (Building Permits)",
}


def _sha_id(text: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()
    return str(uuid.UUID(h[:32]))


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
    return [c for c in chunks if len(c.strip()) > 50]


def _embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("embedding")
    except requests.RequestException as exc:
        log.warning(f"Embedding failed: {exc}")
        return None


def _upsert_batch(points: list[dict]) -> int:
    uploaded = 0
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i: i + BATCH_SIZE]
        try:
            resp = requests.put(
                f"{QDRANT_URL}/collections/{COLLECTION}/points",
                headers=QDRANT_HEADERS,
                json={"points": batch},
                timeout=30,
            )
            if resp.status_code == 200:
                uploaded += len(batch)
            else:
                log.warning(f"Qdrant upsert returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            log.warning(f"Qdrant upsert failed: {exc}")
    return uploaded


def ensure_collection() -> bool:
    try:
        r = requests.get(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            headers=QDRANT_HEADERS,
            timeout=5,
        )
        if r.status_code == 200:
            log.info(f"Collection {COLLECTION} exists")
            return True
        requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            headers=QDRANT_HEADERS,
            json={"vectors": {"size": 768, "distance": "Cosine"}},
            timeout=10,
        )
        log.info(f"Created collection {COLLECTION}")
        return True
    except requests.RequestException as exc:
        log.error(f"Failed to ensure collection: {exc}")
        return False


# =========================================================================
# Source 1: FRED Housing/Construction Macro Series
# =========================================================================

def fetch_fred_re_series() -> int:
    if not FRED_API_KEY:
        log.error("FRED_API_KEY not set in environment")
        return 0

    total_points: list[dict] = []

    for series_id, label in FRED_RE_SERIES.items():
        log.info(f"Fetching FRED series: {series_id} ({label})")
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 60,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                log.warning(f"FRED returned {resp.status_code} for {series_id}")
                continue

            observations = resp.json().get("observations", [])
            if not observations:
                log.warning(f"No observations for {series_id}")
                continue

            text_block = f"FRED Series: {label} ({series_id})\n"
            text_block += f"Last {len(observations)} observations (most recent first):\n\n"
            for obs in observations:
                date = obs.get("date", "")
                value = obs.get("value", ".")
                text_block += f"  {date}: {value}\n"

            for i, chunk in enumerate(_chunk_text(text_block)):
                emb = _embed(chunk)
                if not emb:
                    continue
                total_points.append({
                    "id": _sha_id(f"fred_re:{series_id}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "fred_api",
                        "series": label,
                        "series_id": series_id,
                        "persona": "real_estate",
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        except requests.RequestException as exc:
            log.warning(f"FRED request failed for {series_id}: {exc}")
            continue

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"FRED RE series: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


# =========================================================================
# Source 2: Local CSV/JSON Drop Zone
# =========================================================================

def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _csv_to_sentences(filepath: Path) -> str:
    """Convert CSV rows into natural-language sentences for embedding."""
    sentences = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return ""
            for row_num, row in enumerate(reader):
                parts = [f"{k}: {v}" for k, v in row.items() if v and v.strip()]
                if parts:
                    sentences.append(f"Record {row_num + 1} — " + " | ".join(parts))
                if row_num >= 500:
                    break
    except Exception as exc:
        log.warning(f"CSV parse error for {filepath.name}: {exc}")
        return ""
    return "\n".join(sentences)


def _json_to_text(filepath: Path) -> str:
    """Flatten JSON into readable text blocks."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning(f"JSON parse error for {filepath.name}: {exc}")
        return ""

    def _flatten(obj: object, prefix: str = "") -> list[str]:
        lines = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                lines.extend(_flatten(v, f"{prefix}{k}: " if prefix else f"{k}: "))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                lines.extend(_flatten(item, f"{prefix}[{i}] "))
        else:
            lines.append(f"{prefix}{obj}")
        return lines

    flat_lines = _flatten(data)
    return "\n".join(flat_lines[:1000])


def ingest_local_files() -> int:
    if not DROP_ZONE.exists():
        log.info(f"Drop zone does not exist: {DROP_ZONE}")
        return 0

    csv_files = list(DROP_ZONE.glob("*.csv"))
    json_files = list(DROP_ZONE.glob("*.json"))
    all_files = csv_files + json_files

    if not all_files:
        log.info("Drop zone is empty — no CSV or JSON files found")
        return 0

    log.info(f"Found {len(csv_files)} CSV + {len(json_files)} JSON files in drop zone")
    total_points: list[dict] = []

    for filepath in all_files:
        log.info(f"  Processing: {filepath.name}")

        try:
            if filepath.suffix.lower() == ".csv":
                text = _csv_to_sentences(filepath)
            else:
                text = _json_to_text(filepath)

            if not text or len(text.strip()) < 50:
                log.warning(f"  Skipped {filepath.name} — insufficient content")
                continue

            content_id = _content_hash(text)

            for i, chunk in enumerate(_chunk_text(text)):
                emb = _embed(chunk)
                if not emb:
                    continue
                total_points.append({
                    "id": _sha_id(f"local_re:{filepath.name}:{content_id}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": f"local_{filepath.suffix.lstrip('.')}",
                        "filename": filepath.name,
                        "persona": "real_estate",
                        "content_hash": content_id,
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        except Exception as exc:
            log.warning(f"  Error processing {filepath.name}: {exc}")
            continue

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"Local files: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


# =========================================================================
# Main
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Real estate data ingestion for real_estate_intel")
    parser.add_argument("--fred-only", action="store_true", help="Only fetch FRED macro series")
    parser.add_argument("--local-only", action="store_true", help="Only ingest local CSV/JSON files")
    args = parser.parse_args()

    log.info("Real Estate Data Ingestion starting")

    if not ensure_collection():
        log.error("Cannot ensure Qdrant collection — aborting")
        sys.exit(1)

    total = 0

    if not args.local_only:
        total += fetch_fred_re_series()

    if not args.fred_only:
        total += ingest_local_files()

    log.info(f"Ingestion complete: {total} total vectors upserted into {COLLECTION}")


if __name__ == "__main__":
    main()
