#!/usr/bin/env python3
"""
FORTRESS PRIME — Macro Data Ingestion (Autonomous Swarm Directive — Section VI)
================================================================================
Populates the fed_watcher_intel Qdrant collection with:
  1. 12 FRED economic series (rates, yields, money supply, CPI, GDP, etc.)
  2. FOMC press releases via Federal Reserve RSS feed
  3. FOMC meeting minutes via HTML scrape

Cron: 0 4 * * * (daily, before market sentinel at 06:00)
       0 14 * * * --fomc-only (on FOMC days, after press conference)

Run:  python3 src/ingest_macro_data.py
      python3 src/ingest_macro_data.py --fomc-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_macro_data")

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://192.168.0.100:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

COLLECTION = "fed_watcher_intel"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100

FRED_SERIES = {
    "FEDFUNDS": "Federal Funds Effective Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Spread (Yield Curve)",
    "M2SL": "M2 Money Stock",
    "WALCL": "Fed Balance Sheet Total Assets",
    "RRPONTSYD": "Overnight Reverse Repo",
    "DPCREDIT": "Discount Window Primary Credit",
    "CPIAUCSL": "Consumer Price Index (CPI)",
    "UNRATE": "Unemployment Rate",
    "GDP": "Gross Domestic Product",
    "MORTGAGE30US": "30-Year Fixed Mortgage Rate",
}

FOMC_RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
FOMC_MINUTES_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

QDRANT_HEADERS: dict[str, str] = {}
if QDRANT_API_KEY:
    QDRANT_HEADERS["api-key"] = QDRANT_API_KEY


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
    except Exception as exc:
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
                timeout=120,
            )
            if resp.status_code == 200:
                uploaded += len(batch)
            else:
                log.warning(f"Qdrant upsert returned {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            log.warning(f"Qdrant upsert failed: {exc}")
    return uploaded


def ensure_collection() -> bool:
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", headers=QDRANT_HEADERS, timeout=5)
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
    except Exception as exc:
        log.error(f"Failed to ensure collection: {exc}")
        return False


def fetch_fred_series() -> int:
    if not FRED_API_KEY:
        log.error("FRED_API_KEY not set in environment")
        return 0

    total_points = []

    for series_id, label in FRED_SERIES.items():
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
                    "id": _sha_id(f"fred:{series_id}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "fred_api",
                        "series": label,
                        "series_id": series_id,
                        "persona": "fed_watcher",
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        except requests.RequestException as exc:
            log.warning(f"FRED request failed for {series_id}: {exc}")
            continue

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"FRED series: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", parser.get_text()).strip()


def fetch_fomc_releases() -> int:
    log.info("Fetching FOMC press releases via RSS")
    total_points = []

    try:
        resp = requests.get(FOMC_RSS_URL, timeout=15)
        if resp.status_code != 200:
            log.warning(f"FOMC RSS returned {resp.status_code}")
            return 0

        items = re.findall(
            r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<description>(.*?)</description>.*?</item>",
            resp.text,
            re.DOTALL,
        )

        for title, link, description in items[:20]:
            title = _html_to_text(title)
            description = _html_to_text(description)
            text_block = f"FOMC Press Release: {title}\nSource: {link}\n\n{description}"

            for i, chunk in enumerate(_chunk_text(text_block)):
                emb = _embed(chunk)
                if not emb:
                    continue
                total_points.append({
                    "id": _sha_id(f"fomc_release:{link}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "fomc_press_release",
                        "title": title[:200],
                        "url": link,
                        "persona": "fed_watcher",
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

    except requests.RequestException as exc:
        log.warning(f"FOMC RSS fetch failed: {exc}")
        return 0

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"FOMC releases: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


def fetch_fomc_minutes() -> int:
    log.info("Fetching FOMC meeting minutes")
    total_points = []

    try:
        resp = requests.get(FOMC_MINUTES_URL, timeout=15)
        if resp.status_code != 200:
            log.warning(f"FOMC calendar page returned {resp.status_code}")
            return 0

        minute_links = re.findall(
            r'href="(/monetarypolicy/fomcminutes\d{8}\.htm)"',
            resp.text,
        )

        for rel_link in minute_links[:4]:
            full_url = f"https://www.federalreserve.gov{rel_link}"
            log.info(f"  Fetching minutes: {full_url}")
            try:
                mresp = requests.get(full_url, timeout=30)
                if mresp.status_code != 200:
                    continue
                text = _html_to_text(mresp.text)
                if len(text) < 200:
                    continue

                for i, chunk in enumerate(_chunk_text(text)):
                    emb = _embed(chunk)
                    if not emb:
                        continue
                    total_points.append({
                        "id": _sha_id(f"fomc_minutes:{rel_link}:{i}"),
                        "vector": emb,
                        "payload": {
                            "text": chunk,
                            "source": "fomc_minutes",
                            "url": full_url,
                            "persona": "fed_watcher",
                            "chunk_index": i,
                            "ingested_at": datetime.now(timezone.utc).isoformat(),
                        },
                    })
            except requests.RequestException as exc:
                log.warning(f"Minutes fetch failed for {rel_link}: {exc}")
                continue

    except requests.RequestException as exc:
        log.warning(f"FOMC calendar fetch failed: {exc}")
        return 0

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"FOMC minutes: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Macro data ingestion for fed_watcher_intel")
    parser.add_argument("--fomc-only", action="store_true", help="Only fetch FOMC releases and minutes")
    args = parser.parse_args()

    log.info("Macro Data Ingestion starting")

    if not ensure_collection():
        log.error("Cannot ensure Qdrant collection — aborting")
        sys.exit(1)

    total = 0

    if not args.fomc_only:
        total += fetch_fred_series()

    total += fetch_fomc_releases()
    total += fetch_fomc_minutes()

    log.info(f"Ingestion complete: {total} total vectors upserted into {COLLECTION}")


if __name__ == "__main__":
    main()
