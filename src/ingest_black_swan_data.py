#!/usr/bin/env python3
"""
FORTRESS PRIME — Black Swan Data Ingestion (Black Swan Hunter Persona)
======================================================================
Populates the black_swan_intel Qdrant collection with:
  1. Market tail-risk indicators (VIX, VVIX, SKEW via yfinance)
  2. Credit/liquidity stress series (High Yield OAS, Corporate OAS, Financial Stress via FRED)
  3. Geopolitical crisis feeds (UN Peace & Security, BBC World News via RSS)

Cron: 30 4 * * * (daily, after real estate ingestion at 04:15)

Run:  python3 src/ingest_black_swan_data.py
      python3 src/ingest_black_swan_data.py --indicators-only
      python3 src/ingest_black_swan_data.py --rss-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import requests
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_black_swan")

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

QDRANT_HEADERS: dict[str, str] = {}
if QDRANT_API_KEY:
    QDRANT_HEADERS["api-key"] = QDRANT_API_KEY

COLLECTION = "black_swan_intel"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100

TAIL_RISK_TICKERS = ["^VIX", "^VVIX", "^SKEW"]
TAIL_RISK_LABELS = {
    "^VIX": ("VIX", "CBOE Volatility Index", 25, 35),
    "^VVIX": ("VVIX", "CBOE VIX of VIX", 120, 150),
    "^SKEW": ("SKEW", "CBOE Skew Index", 140, 155),
}

FRED_STRESS_SERIES = {
    "BAMLH0A0HYM2": "ICE BofA High Yield Option-Adjusted Spread",
    "BAMLC0A0CM": "ICE BofA Corporate Option-Adjusted Spread",
    "STLFSI4": "St. Louis Fed Financial Stress Index",
}

CRISIS_FEEDS = {
    "UN Peace & Security": "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml",
    "BBC World News": "https://feeds.bbci.co.uk/news/world/rss.xml",
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
# Source 1: Market Tail-Risk Indicators (yfinance)
# =========================================================================

def _classify_level(value: float, warn: float, critical: float) -> str:
    if value >= critical:
        return "CRISIS"
    if value >= warn:
        return "ELEVATED"
    return "NORMAL"


def fetch_tail_risk_snapshot() -> int:
    log.info("Fetching tail-risk indicators via yfinance")
    total_points: list[dict] = []
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=30)

    try:
        data = yf.download(
            TAIL_RISK_TICKERS,
            start=str(start),
            end=str(today),
            auto_adjust=True,
            progress=False,
            timeout=15,
        )
    except Exception as exc:
        log.warning(f"yfinance download failed: {exc}")
        return 0

    if data.empty:
        log.warning("yfinance returned empty data for tail-risk tickers")
        return 0

    if isinstance(data.columns, __import__("pandas").MultiIndex):
        close = data.get("Close", data)
    else:
        close = data

    close = close.dropna(how="all")
    if close.empty:
        return 0

    friendly = {t: t.replace("^", "") for t in TAIL_RISK_TICKERS}
    close = close.rename(columns=friendly)

    dashboard_lines = [
        f"Black Swan Tail-Risk Dashboard ({today.isoformat()})",
        "=" * 50,
    ]

    for ticker in TAIL_RISK_TICKERS:
        short = ticker.replace("^", "")
        label_info = TAIL_RISK_LABELS.get(ticker)
        if not label_info or short not in close.columns:
            continue
        short_name, full_name, warn, crit = label_info
        latest = close[short].dropna()
        if latest.empty:
            continue
        val = float(latest.iloc[-1])
        level = _classify_level(val, warn, crit)
        dashboard_lines.append(f"  {short_name} ({full_name}): {val:.2f} [{level}]")

    dashboard_lines.append("")
    dashboard_lines.append("30-Day Time Series:")
    for col in close.columns:
        series_str = ", ".join(
            f"{idx.strftime('%m/%d')}:{v:.2f}"
            for idx, v in close[col].dropna().items()
        )
        dashboard_lines.append(f"  {col}: {series_str}")

    text_block = "\n".join(dashboard_lines)

    for i, chunk in enumerate(_chunk_text(text_block)):
        emb = _embed(chunk)
        if not emb:
            continue
        total_points.append({
            "id": _sha_id(f"tail_risk:{today.isoformat()}:{i}"),
            "vector": emb,
            "payload": {
                "text": chunk,
                "source": "yfinance_tail_risk",
                "persona": "black_swan",
                "chunk_index": i,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"Tail-risk indicators: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


# =========================================================================
# Source 2: Credit & Liquidity Stress (FRED API)
# =========================================================================

def fetch_fred_stress_series() -> int:
    if not FRED_API_KEY:
        log.error("FRED_API_KEY not set in environment")
        return 0

    total_points: list[dict] = []

    for series_id, label in FRED_STRESS_SERIES.items():
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

            text_block = f"FRED Stress Series: {label} ({series_id})\n"
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
                    "id": _sha_id(f"fred_stress:{series_id}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "fred_api",
                        "series": label,
                        "series_id": series_id,
                        "persona": "black_swan",
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        except requests.RequestException as exc:
            log.warning(f"FRED request failed for {series_id}: {exc}")
            continue

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"FRED stress series: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


# =========================================================================
# Source 3: Geopolitical Crisis RSS Feeds
# =========================================================================

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(text: str) -> str:
    p = _HTMLStripper()
    p.feed(text)
    return re.sub(r"\s+", " ", p.get_text()).strip()


def fetch_crisis_feeds() -> int:
    log.info("Fetching geopolitical crisis RSS feeds")
    total_points: list[dict] = []

    for feed_name, feed_url in CRISIS_FEEDS.items():
        log.info(f"  Feed: {feed_name}")
        try:
            resp = requests.get(feed_url, timeout=15)
            if resp.status_code != 200:
                log.warning(f"  RSS returned {resp.status_code} for {feed_name}")
                continue

            items = re.findall(
                r"<item>.*?<title>(.*?)</title>.*?(?:<description>(.*?)</description>)?.*?</item>",
                resp.text,
                re.DOTALL,
            )

            text_blocks = []
            for title_raw, desc_raw in items[:20]:
                title = _strip_html(title_raw)
                desc = _strip_html(desc_raw) if desc_raw else ""
                entry = f"[{feed_name}] {title}"
                if desc:
                    entry += f" | {desc[:300]}"
                text_blocks.append(entry)

            if not text_blocks:
                log.warning(f"  No items parsed from {feed_name}")
                continue

            combined = "\n\n".join(text_blocks)
            today = datetime.now(timezone.utc).date().isoformat()

            for i, chunk in enumerate(_chunk_text(combined)):
                emb = _embed(chunk)
                if not emb:
                    continue
                total_points.append({
                    "id": _sha_id(f"rss_crisis:{feed_name}:{today}:{i}"),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "rss_crisis",
                        "feed_name": feed_name,
                        "persona": "black_swan",
                        "chunk_index": i,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        except requests.RequestException as exc:
            log.warning(f"  RSS fetch failed for {feed_name}: {exc}")
            continue

    if total_points:
        uploaded = _upsert_batch(total_points)
        log.info(f"Crisis feeds: {uploaded}/{len(total_points)} vectors upserted")
        return uploaded
    return 0


# =========================================================================
# Main
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Black Swan tail-risk data ingestion")
    parser.add_argument("--indicators-only", action="store_true", help="VIX/VVIX/SKEW + FRED only")
    parser.add_argument("--rss-only", action="store_true", help="Crisis RSS feeds only")
    args = parser.parse_args()

    log.info("Black Swan Data Ingestion starting")

    if not ensure_collection():
        log.error("Cannot ensure Qdrant collection — aborting")
        sys.exit(1)

    total = 0

    if not args.rss_only:
        total += fetch_tail_risk_snapshot()
        total += fetch_fred_stress_series()

    if not args.indicators_only:
        total += fetch_crisis_feeds()

    log.info(f"Ingestion complete: {total} total vectors upserted into {COLLECTION}")


if __name__ == "__main__":
    main()
