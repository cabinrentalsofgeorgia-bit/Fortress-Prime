#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — UNIVERSAL INTELLIGENCE HUNTER
═══════════════════════════════════════════════════════════════════════════════
Reads all 9 persona configs and ingests content from multiple sources into
their respective Qdrant vector collections.

Sources handled:
  1. Local files on NAS  (PDF, TXT, MD, HTML, CSV)
  2. Web scraping         (Substacks, newsletters, FRED data)
  3. RSS / Atom feeds     (blog posts, news)
  4. FRED economic data   (for Fed Watcher)
  5. Existing Fortress-Prime documents (for all personas)

Usage:
    # Ingest everything for all personas
    python src/universal_intelligence_hunter.py --all

    # Single persona
    python src/universal_intelligence_hunter.py --persona jordi

    # Specific source type
    python src/universal_intelligence_hunter.py --persona fed_watcher --source fred

    # Dry run (show what would be ingested)
    python src/universal_intelligence_hunter.py --all --dry-run

    # Status check
    python src/universal_intelligence_hunter.py --status

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import time
import uuid
import hashlib
import argparse
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hunter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERSONAS_DIR = PROJECT_ROOT / "personas"
INTEL_BASE   = Path("/mnt/fortress_nas/Intelligence")
STATE_FILE   = INTEL_BASE / "hunter_state.json"

QDRANT_URL     = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY, "Content-Type": "application/json"}

OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://localhost:11434")
NGINX_LB    = os.getenv("NGINX_LB_URL", "http://192.168.0.100")
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM   = 768

CHUNK_SIZE    = 1000   # characters
CHUNK_OVERLAP = 200

# Map persona slugs → NAS directory names
SLUG_TO_DIR = {
    "jordi":       "Jordi_Visser",
    "raoul":       "Raoul_Pal",
    "lyn":         "Lyn_Alden",
    "vol_trader":  "Vol_Trader",
    "fed_watcher": "Fed_Watcher",
    "sound_money": "Sound_Money",
    "real_estate": "Real_Estate",
    "permabear":   "Permabear",
    "black_swan":  "Black_Swan",
}

# Allowed file extensions for local ingestion
INGEST_EXTS = {".md", ".txt", ".pdf", ".html", ".csv", ".json"}

# ---------------------------------------------------------------------------
# State management (deduplication)
# ---------------------------------------------------------------------------

def load_state() -> Dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"ingested": {}}   # slug → [file_hash, ...]


def save_state(state: Dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(path: Path) -> str:
    """Extract readable text from a file."""
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".md", ".txt", ".csv"):
        return path.read_text(errors="ignore")
    if ext == ".html":
        return _strip_html(path.read_text(errors="ignore"))
    if ext == ".json":
        try:
            data = json.loads(path.read_text(errors="ignore"))
            return json.dumps(data, indent=2)
        except Exception:
            return path.read_text(errors="ignore")
    return ""


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            txt = page.extract_text()
            if txt:
                pages.append(txt)
        return "\n\n".join(pages)
    except Exception as e:
        log.warning("PDF extraction failed for %s: %s", path.name, e)
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        piece = text[start:end]
        if end < len(text):
            bp = max(piece.rfind("."), piece.rfind("?"), piece.rfind("!"))
            if bp > size * 0.5:
                piece = piece[: bp + 1]
                end = start + bp + 1
        stripped = piece.strip()
        if len(stripped) > 60:
            chunks.append(stripped)
        start = end - overlap
    return chunks

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding via Nginx LB (distributes across 4 Spark nodes)."""
    for url in [f"{NGINX_LB}/api/embeddings", f"{OLLAMA_URL}/api/embeddings"]:
        try:
            r = requests.post(
                url,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=60,
            )
            r.raise_for_status()
            emb = r.json().get("embedding")
            if emb and len(emb) == EMBED_DIM:
                return emb
        except Exception:
            continue
    log.error("Embedding failed on all endpoints")
    return None

# ---------------------------------------------------------------------------
# Qdrant upload
# ---------------------------------------------------------------------------

def upload_points(collection: str, points: List[Dict]) -> int:
    uploaded = 0
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        try:
            r = requests.put(
                f"{QDRANT_URL}/collections/{collection}/points",
                headers=QDRANT_HEADERS,
                json={"points": batch},
                timeout=120,
            )
            if r.status_code in (200, 201):
                uploaded += len(batch)
            else:
                log.error("Upload batch failed: %s", r.text[:200])
        except Exception as e:
            log.error("Upload error: %s", e)
    return uploaded

# ---------------------------------------------------------------------------
# Core ingestion: local files → vectors
# ---------------------------------------------------------------------------

def ingest_file(
    path: Path,
    collection: str,
    persona_slug: str,
    source_label: str = "local",
) -> int:
    """Ingest one file into a persona's Qdrant collection. Returns vector count."""
    text = extract_text(path)
    if len(text) < 80:
        return 0

    chunks = chunk_text(text)
    points = []

    for i, chunk in enumerate(chunks):
        emb = embed_text(chunk)
        if not emb:
            continue
        hx = hashlib.sha256(f"{path}:{i}".encode()).hexdigest()[:32]
        points.append({
            "id": str(uuid.UUID(hx)),
            "vector": emb,
            "payload": {
                "text": chunk,
                "source_file": str(path),
                "file_name": path.name,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "persona": persona_slug,
                "source": source_label,
                "ingested_at": datetime.now().isoformat(),
            },
        })

    if not points:
        return 0

    uploaded = upload_points(collection, points)
    return uploaded

# ---------------------------------------------------------------------------
# Source: local NAS directory scan
# ---------------------------------------------------------------------------

def ingest_local_files(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """Scan NAS Intelligence/{persona}/ and ingest new files."""
    nas_dir = INTEL_BASE / SLUG_TO_DIR.get(slug, slug)
    if not nas_dir.exists():
        log.info("  NAS dir missing: %s", nas_dir)
        return 0

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for fpath in sorted(nas_dir.rglob("*")):
        if fpath.is_dir():
            continue
        if fpath.suffix.lower() not in INGEST_EXTS:
            continue
        if "@eaDir" in str(fpath):
            continue

        fh = file_hash(fpath)
        if fh in ingested_hashes:
            continue

        if dry_run:
            log.info("  [DRY] Would ingest: %s (%s)", fpath.name, fpath.suffix)
            total += 1
            continue

        log.info("  Ingesting: %s", fpath.name)
        count = ingest_file(fpath, collection, slug, source_label="nas")
        if count > 0:
            ingested_hashes.add(fh)
            state.setdefault("ingested", {}).setdefault(slug, []).append(fh)
            save_state(state)
            total += count
            log.info("    -> %d vectors", count)

    return total

# ---------------------------------------------------------------------------
# Source: Fortress-Prime project docs (shared across relevant personas)
# ---------------------------------------------------------------------------

PERSONA_DOC_KEYWORDS = {
    "jordi":       ["bitcoin", "crypto", "ai", "nvidia", "semiconductor", "tech"],
    "raoul":       ["liquidity", "macro", "m2", "cycle", "central bank", "crypto"],
    "lyn":         ["energy", "bitcoin", "gold", "inflation", "sound money", "fiscal"],
    "vol_trader":  ["volatility", "gamma", "options", "dealer", "vix", "squeeze"],
    "fed_watcher": ["fed", "fomc", "rate", "monetary", "treasury", "inflation", "qe"],
    "sound_money": ["gold", "bitcoin", "fiat", "debase", "inflation", "sound money"],
    "real_estate": ["cabin", "rental", "property", "real estate", "crog", "occupancy",
                     "revenue", "guest", "airbnb", "vrbo", "management"],
    "permabear":   ["crash", "bubble", "overvalued", "credit", "debt", "recession"],
    "black_swan":  ["tail risk", "black swan", "convexity", "hedge", "volatility",
                     "systemic", "crisis"],
}


def ingest_project_docs(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """Scan Fortress-Prime *.md docs and ingest those relevant to this persona."""
    keywords = PERSONA_DOC_KEYWORDS.get(slug, [])
    if not keywords:
        return 0

    doc_dirs = [PROJECT_ROOT, PROJECT_ROOT / "docs"]
    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for d in doc_dirs:
        if not d.is_dir():
            continue
        for fpath in sorted(d.glob("*.md")):
            fh = file_hash(fpath)
            if fh in ingested_hashes:
                continue

            content = fpath.read_text(errors="ignore").lower()
            hits = sum(1 for kw in keywords if kw in content)
            if hits < 2:
                continue

            if dry_run:
                log.info("  [DRY] Would ingest doc: %s (keyword hits: %d)", fpath.name, hits)
                total += 1
                continue

            log.info("  Ingesting doc: %s (keyword hits: %d)", fpath.name, hits)
            count = ingest_file(fpath, collection, slug, source_label="project_docs")
            if count > 0:
                ingested_hashes.add(fh)
                state.setdefault("ingested", {}).setdefault(slug, []).append(fh)
                save_state(state)
                total += count

    return total

# ---------------------------------------------------------------------------
# Source: FRED economic data (Fed Watcher persona)
# ---------------------------------------------------------------------------

FRED_SERIES = {
    "FEDFUNDS":     "Federal Funds Effective Rate",
    "DGS10":        "10-Year Treasury Yield",
    "DGS2":         "2-Year Treasury Yield",
    "T10Y2Y":       "10Y-2Y Spread (Yield Curve)",
    "M2SL":         "M2 Money Stock",
    "WALCL":        "Fed Balance Sheet Total Assets",
    "RRPONTSYD":    "Overnight Reverse Repo",
    "DPCREDIT":     "Discount Window Primary Credit",
    "CPIAUCSL":     "Consumer Price Index (CPI)",
    "UNRATE":       "Unemployment Rate",
    "GDP":          "Gross Domestic Product",
    "MORTGAGE30US": "30-Year Fixed Mortgage Rate",
}


def fetch_fred_data(state: Dict, dry_run: bool = False) -> int:
    """Fetch key FRED series and ingest as text for fed_watcher_intel."""
    fred_key = os.getenv("FRED_API_KEY", "")
    collection = "fed_watcher_intel"
    slug = "fed_watcher"

    texts = []

    if fred_key:
        log.info("  Fetching FRED data with API key...")
        for series_id, label in FRED_SERIES.items():
            try:
                url = (
                    f"https://api.stlouisfed.org/fred/series/observations"
                    f"?series_id={series_id}&api_key={fred_key}"
                    f"&file_type=json&sort_order=desc&limit=60"
                )
                r = requests.get(url, timeout=15)
                if r.status_code != 200:
                    continue
                obs = r.json().get("observations", [])
                if not obs:
                    continue

                lines = [f"# {label} ({series_id})", f"Recent observations (most recent first):", ""]
                for o in obs[:60]:
                    lines.append(f"  {o['date']}: {o['value']}")
                text = "\n".join(lines)
                texts.append((f"FRED_{series_id}", text))
                if dry_run:
                    log.info("  [DRY] Would ingest FRED %s (%d obs)", series_id, len(obs))
            except Exception as e:
                log.warning("  FRED %s failed: %s", series_id, e)
    else:
        log.info("  No FRED_API_KEY — generating synthesized macro reference data")
        macro_text = _generate_macro_reference()
        texts.append(("macro_reference", macro_text))

    if dry_run:
        return len(texts)

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for label, text in texts:
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if content_hash in ingested_hashes:
            continue

        chunks = chunk_text(text)
        points = []
        for i, chunk in enumerate(chunks):
            emb = embed_text(chunk)
            if not emb:
                continue
            hx = hashlib.sha256(f"fred:{label}:{i}".encode()).hexdigest()[:32]
            points.append({
                "id": str(uuid.UUID(hx)),
                "vector": emb,
                "payload": {
                    "text": chunk,
                    "source": "fred_api" if os.getenv("FRED_API_KEY") else "macro_reference",
                    "series": label,
                    "persona": slug,
                    "chunk_index": i,
                    "ingested_at": datetime.now().isoformat(),
                },
            })

        if points:
            uploaded = upload_points(collection, points)
            total += uploaded
            ingested_hashes.add(content_hash)
            state.setdefault("ingested", {}).setdefault(slug, []).append(content_hash)
            save_state(state)
            log.info("    -> %s: %d vectors", label, uploaded)

    return total


def _generate_macro_reference() -> str:
    """Generate a comprehensive macro economics reference document for Fed Watcher."""
    return """# Federal Reserve & Macro Economics Reference
## Key Interest Rates (Feb 2026)
- Federal Funds Rate: 4.25-4.50% (after 100bps of cuts in 2024)
- 10-Year Treasury: ~4.5%
- 2-Year Treasury: ~4.2%
- 30-Year Mortgage: ~6.8%
- Yield curve: Normalizing after historic inversion (2022-2024)

## Fed Balance Sheet
- Total Assets: ~$6.8T (down from $8.9T peak Apr 2022)
- QT pace: $60B/month Treasuries + $35B/month MBS (reduced from $95B in mid-2024)
- Overnight RRP: declining as money market funds reallocate

## FOMC Meeting Schedule 2026
- Jan 28-29, Mar 18-19, May 6-7, Jun 17-18, Jul 29-30, Sep 16-17, Nov 4-5, Dec 16-17
- Dot plot published: Mar, Jun, Sep, Dec

## Key Economic Indicators
- GDP growth: ~2.5% (moderating)
- CPI: ~2.8% (sticky above 2% target)
- Core PCE: ~2.6%
- Unemployment: ~4.2% (rising slowly from 3.4% cycle low)
- ISM Manufacturing: ~49 (contraction territory)
- ISM Services: ~53 (expansion)

## Fed Policy Framework
- Dual mandate: Maximum employment + price stability (2% inflation target)
- SEP (Summary of Economic Projections) key focus
- Dot plot signals future rate path
- Forward guidance through FOMC statements and press conferences
- Quantitative Tightening (QT) reduces balance sheet

## Market Impact Channels
- Rate cuts → lower mortgage rates → housing recovery
- Rate cuts → weaker dollar → commodity/crypto bid
- QT end → liquidity injection → risk asset rally
- Balance sheet expansion → money supply increase → inflation risk
- Yield curve normalization → bank lending recovery

## Historical Parallels
- 2019 insurance cuts: 3 cuts then pause → market rallied
- 2020 emergency cuts: 150bps + unlimited QE → massive asset inflation
- 2022-2023 tightening: 525bps fastest hike cycle → crypto winter, bank failures
- 2024 pivot: First cut Sep 2024, markets front-ran by 6 months

## Critical Signals to Watch
1. FOMC statement language changes ("further" vs "any" rate changes)
2. Dot plot median shift
3. RRP facility drawdown rate
4. Bank reserves at Fed (WRESBAL)
5. Treasury General Account (TGA) balance
6. Credit spreads (IG and HY)
7. Breakeven inflation rates
8. Employment cost index (ECI)
"""

# ---------------------------------------------------------------------------
# Source: web content (RSS / Substack scraping)
# ---------------------------------------------------------------------------

PERSONA_FEEDS = {
    "jordi": [
        ("substack", "https://visserlabs.substack.com/feed"),
    ],
    "raoul": [
        ("substack", "https://raoulpal.substack.com/feed"),
    ],
    "lyn": [
        ("rss", "https://www.lynalden.com/feed/"),
    ],
    "fed_watcher": [
        ("rss", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ],
    "permabear": [
        ("rss", "https://www.hussmanfunds.com/comment/mc/rss.xml"),
    ],
    "sound_money": [
        ("rss", "https://schiffgold.com/feed/"),
    ],
}


def fetch_rss_content(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """Fetch RSS/Atom feeds and ingest articles."""
    feeds = PERSONA_FEEDS.get(slug, [])
    if not feeds:
        return 0

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for feed_type, url in feeds:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Fortress-Prime/1.0"})
            if r.status_code != 200:
                log.warning("  Feed %s returned %d", url, r.status_code)
                continue

            articles = _parse_feed_xml(r.text)
            log.info("  Feed %s: %d articles found", url, len(articles))

            for article in articles:
                content_hash = hashlib.sha256(article["title"].encode()).hexdigest()[:16]
                if content_hash in ingested_hashes:
                    continue

                text = f"# {article['title']}\n\n{article.get('description', '')}\n\n{article.get('content', '')}"
                text = _strip_html(text)

                if len(text) < 100:
                    continue

                if dry_run:
                    log.info("  [DRY] Would ingest: %s", article["title"][:80])
                    total += 1
                    continue

                chunks = chunk_text(text)
                points = []
                for i, chunk in enumerate(chunks):
                    emb = embed_text(chunk)
                    if not emb:
                        continue
                    hx = hashlib.sha256(f"rss:{slug}:{content_hash}:{i}".encode()).hexdigest()[:32]
                    points.append({
                        "id": str(uuid.UUID(hx)),
                        "vector": emb,
                        "payload": {
                            "text": chunk,
                            "source": "rss_feed",
                            "feed_url": url,
                            "title": article["title"],
                            "published": article.get("published", ""),
                            "persona": slug,
                            "chunk_index": i,
                            "ingested_at": datetime.now().isoformat(),
                        },
                    })

                if points:
                    uploaded = upload_points(collection, points)
                    total += uploaded
                    ingested_hashes.add(content_hash)
                    state.setdefault("ingested", {}).setdefault(slug, []).append(content_hash)
                    save_state(state)
                    log.info("    -> %s: %d vectors", article["title"][:60], uploaded)

        except Exception as e:
            log.warning("  Feed fetch error (%s): %s", url, e)

    return total


def _parse_feed_xml(xml_text: str) -> List[Dict]:
    """Lightweight RSS/Atom parser without external dependencies."""
    articles = []
    # Try RSS <item> tags
    items = re.findall(r"<item>(.*?)</item>", xml_text, re.S)
    if not items:
        # Try Atom <entry> tags
        items = re.findall(r"<entry>(.*?)</entry>", xml_text, re.S)

    for item in items:
        title = _xml_tag(item, "title")
        desc = _xml_tag(item, "description") or _xml_tag(item, "summary")
        content = _xml_tag(item, "content:encoded") or _xml_tag(item, "content")
        published = _xml_tag(item, "pubDate") or _xml_tag(item, "published") or _xml_tag(item, "updated")
        if title:
            articles.append({
                "title": _strip_html(title),
                "description": desc or "",
                "content": content or "",
                "published": published or "",
            })

    return articles[:20]  # Cap at 20 articles per feed


def _xml_tag(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
    if m:
        text = m.group(1).strip()
        if text.startswith("<![CDATA["):
            text = text[9:]
            if text.endswith("]]>"):
                text = text[:-3]
        return text
    return ""

# ---------------------------------------------------------------------------
# Source: Twitter/X via xAI Grok API (x_search tool)
# ---------------------------------------------------------------------------

PERSONA_X_QUERIES = {
    "jordi": [
        "Jordi Visser macro market analysis Bitcoin crypto AI",
        "triple convergence tech dollar rates market outlook",
    ],
    "raoul": [
        "Raoul Pal macro liquidity banana zone crypto cycle",
        "Real Vision global macro liquidity cycle analysis",
    ],
    "lyn": [
        "Lyn Alden fiscal policy Bitcoin energy inflation analysis",
        "sound money energy economy Bitcoin digital scarcity",
    ],
    "vol_trader": [
        "gamma exposure GEX dealer positioning volatility options market",
        "VIX term structure zero DTE options gamma squeeze market structure",
    ],
    "fed_watcher": [
        "FOMC Federal Reserve rate decision monetary policy update",
        "Fed balance sheet QT reverse repo Treasury yields inflation",
    ],
    "sound_money": [
        "gold Bitcoin sound money fiat debasement central bank buying",
        "de-dollarization BRICS gold reserves hard money inflation hedge",
    ],
    "real_estate": [
        "vacation rental market cabin rental occupancy revenue trends 2026",
        "Airbnb VRBO short term rental regulation dynamic pricing revenue",
    ],
    "permabear": [
        "stock market overvalued bubble credit cycle recession warning",
        "CAPE ratio market cap GDP Buffett indicator crash risk",
    ],
    "black_swan": [
        "tail risk black swan event systemic crisis geopolitical risk",
        "financial system stress credit spreads sovereign debt convexity hedge",
    ],
}


def fetch_x_content(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """
    Search Twitter/X via xAI Grok API (x_search tool) and ingest results.
    Requires XAI_API_KEY in .env.
    """
    xai_key = os.getenv("XAI_API_KEY", "")
    if not xai_key:
        log.info("  No XAI_API_KEY — skipping Twitter/X search for %s", slug)
        return 0

    queries = PERSONA_X_QUERIES.get(slug, [])
    if not queries:
        return 0

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for query in queries:
        try:
            resp = requests.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {xai_key}",
                },
                json={
                    "model": "grok-3-mini-fast",
                    "input": [
                        {"role": "system", "content": (
                            "You are a financial intelligence researcher. "
                            "Summarize the most important recent tweets and posts "
                            "about this topic. Include key data points, opinions, "
                            "and market-moving insights. Format as a structured "
                            "intelligence briefing with bullet points."
                        )},
                        {"role": "user", "content": query},
                    ],
                    "tools": [{"type": "x_search"}],
                },
                timeout=30,
            )

            if resp.status_code != 200:
                log.warning("  xAI search failed (%d): %s", resp.status_code, resp.text[:200])
                continue

            data = resp.json()
            # Extract the text output from the response
            output_text = ""
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text += content.get("text", "")

            if not output_text or len(output_text) < 100:
                log.info("  X search returned thin results for: %s", query[:50])
                continue

            content_hash = hashlib.sha256(output_text[:500].encode()).hexdigest()[:16]
            if content_hash in ingested_hashes:
                continue

            text = f"# Twitter/X Intelligence: {query}\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n{output_text}"

            if dry_run:
                log.info("  [DRY] Would ingest X search: %s (%d chars)", query[:50], len(text))
                total += 1
                continue

            chunks = chunk_text(text)
            points = []
            for i, chunk in enumerate(chunks):
                emb = embed_text(chunk)
                if not emb:
                    continue
                hx = hashlib.sha256(f"x:{slug}:{content_hash}:{i}".encode()).hexdigest()[:32]
                points.append({
                    "id": str(uuid.UUID(hx)),
                    "vector": emb,
                    "payload": {
                        "text": chunk,
                        "source": "twitter_x",
                        "query": query,
                        "persona": slug,
                        "chunk_index": i,
                        "ingested_at": datetime.now().isoformat(),
                    },
                })

            if points:
                uploaded = upload_points(collection, points)
                total += uploaded
                ingested_hashes.add(content_hash)
                state.setdefault("ingested", {}).setdefault(slug, []).append(content_hash)
                save_state(state)
                log.info("    -> X search [%s]: %d vectors", query[:40], uploaded)

        except Exception as e:
            log.warning("  X search error (%s): %s", query[:40], e)

    return total


# ---------------------------------------------------------------------------
# Source: YouTube transcripts via yt-dlp
# ---------------------------------------------------------------------------

# Direct video URLs — curated high-value content for transcript ingestion.
# Add more URLs here as you find valuable interviews/presentations.
# yt-dlp handles auto-generated and manual subtitles from public videos.
PERSONA_YOUTUBE_VIDEOS = {
    "jordi": [
        "https://www.youtube.com/watch?v=jM-OQNtWIJg",  # The ULTIMATE Crypto Bet On AI | Jordi Visser
        "https://www.youtube.com/watch?v=f1UEqoZKTNs",  # Why Bitcoin Is the Only Asset That Will Survive the AI Era
        "https://www.youtube.com/watch?v=_oaKiUspuzA",  # Recession Is Cancelled: Why Bitcoin & Stocks Will Explode
    ],
    "raoul": [
        "https://www.youtube.com/watch?v=s2_Lrrk9Ur4",  # The Next 5 Years Will Reshape the Entire Economy
        "https://www.youtube.com/watch?v=DFgweHxl2pQ",  # This Cycle Might Continue Until 2026
        "https://www.youtube.com/watch?v=Nqy6sUBjXZ8",  # 2026 Crypto Narratives to WATCH
        "https://www.youtube.com/watch?v=y8bZY2qQKJk",  # Why the Fed Is Making a Huge Mistake
    ],
    "lyn": [
        "https://www.youtube.com/watch?v=Giuzcd4oxIk",  # Nothing Stops This Train | Bitcoin 2025
        "https://www.youtube.com/watch?v=eUe2rxjPl-w",  # Why Bitcoin Still Wins In 2025
        "https://www.youtube.com/watch?v=aq7oCrel-4I",  # The Economics of Bitcoin Scaling
        "https://www.youtube.com/watch?v=C1684Wvs1uA",  # Trump, Tariffs, Bitcoin & The Dollar's Fate
    ],
    "fed_watcher": [
        "https://www.youtube.com/watch?v=y8bZY2qQKJk",  # Why the Fed Is Making a Huge Mistake (Raoul + Dan Morehead)
    ],
}


def fetch_youtube_transcripts(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """
    Download YouTube video transcripts via yt-dlp and ingest into persona collection.
    Works for any public video with auto-generated or manual subtitles.
    No API key needed for public transcripts.
    """
    import subprocess
    import tempfile

    videos = PERSONA_YOUTUBE_VIDEOS.get(slug, [])
    if not videos:
        log.info("  No YouTube videos configured for %s", slug)
        return 0

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    total = 0

    for video_url in videos:
        video_hash = hashlib.sha256(video_url.encode()).hexdigest()[:16]
        if video_hash in ingested_hashes:
            continue

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                sub_file = os.path.join(tmpdir, "sub")

                # Download auto-generated subtitles in SRT format (no ffmpeg needed)
                result = subprocess.run(
                    [
                        "yt-dlp",
                        "--skip-download",
                        "--write-auto-sub",
                        "--write-sub",
                        "--sub-lang", "en",
                        "--sub-format", "srt",
                        "-o", sub_file,
                        video_url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                # Find the subtitle file (yt-dlp adds .en.srt suffix)
                sub_files = [f for f in os.listdir(tmpdir) if f.endswith((".srt", ".vtt"))]
                if not sub_files:
                    log.info("  No subtitles found for: %s", video_url)
                    continue

                sub_path = os.path.join(tmpdir, sub_files[0])
                raw_text = open(sub_path, "r", errors="ignore").read()

                # Clean SRT: remove timestamps and sequence numbers
                lines = []
                for line in raw_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.isdigit():
                        continue
                    if "-->" in line:
                        continue
                    # Remove VTT tags
                    cleaned = re.sub(r"<[^>]+>", "", line)
                    if cleaned:
                        lines.append(cleaned)

                # Deduplicate consecutive lines (auto-subs repeat)
                deduped = []
                for line in lines:
                    if not deduped or line != deduped[-1]:
                        deduped.append(line)

                transcript = " ".join(deduped)

                if len(transcript) < 200:
                    log.info("  Transcript too short for: %s (%d chars)", video_url, len(transcript))
                    continue

                # Get video title
                title_result = subprocess.run(
                    ["yt-dlp", "--get-title", video_url],
                    capture_output=True, text=True, timeout=15,
                )
                title = title_result.stdout.strip() or "Unknown Video"

                if dry_run:
                    log.info("  [DRY] Would ingest YT: %s (%d chars)", title[:60], len(transcript))
                    total += 1
                    continue

                text = f"# YouTube Transcript: {title}\n\nSource: {video_url}\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n{transcript}"

                chunks = chunk_text(text)
                points = []
                for i, chunk in enumerate(chunks):
                    emb = embed_text(chunk)
                    if not emb:
                        continue
                    hx = hashlib.sha256(f"yt:{slug}:{video_hash}:{i}".encode()).hexdigest()[:32]
                    points.append({
                        "id": str(uuid.UUID(hx)),
                        "vector": emb,
                        "payload": {
                            "text": chunk,
                            "source": "youtube_transcript",
                            "video_url": video_url,
                            "title": title,
                            "persona": slug,
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "ingested_at": datetime.now().isoformat(),
                        },
                    })

                if points:
                    uploaded = upload_points(collection, points)
                    total += uploaded
                    ingested_hashes.add(video_hash)
                    state.setdefault("ingested", {}).setdefault(slug, []).append(video_hash)
                    save_state(state)
                    log.info("    -> YT [%s]: %d vectors", title[:50], uploaded)

        except subprocess.TimeoutExpired:
            log.warning("  yt-dlp timeout for: %s", video_url)
        except Exception as e:
            log.warning("  YouTube error (%s): %s", video_url, e)

    return total


# ---------------------------------------------------------------------------
# Synthesized seed data for personas with no external sources yet
# ---------------------------------------------------------------------------

SEED_DOCUMENTS = {
    "vol_trader": """# Volatility & Market Structure Reference

## Gamma Exposure (GEX) Framework
Gamma exposure measures how much market makers need to hedge for each point move in the index.
- Positive GEX: Dealers long gamma → sell rips, buy dips → low volatility, mean-reverting
- Negative GEX: Dealers short gamma → buy rips, sell dips → high volatility, trending
- Gamma flip line: The strike where GEX flips from positive to negative
- Zero GEX: Extreme instability — markets can move violently in either direction

## Key Volatility Metrics
- VIX: 30-day implied vol of SPX options (CBOE)
- VIX9D: 9-day implied vol (near-term fear gauge)
- VVIX: Volatility of VIX (tail risk measure)
- SKEW: Put-call skew (demand for downside protection)
- MOVE: Bond market volatility (Merrill Lynch)
- GEX: Gamma exposure (SpotGamma, SqueezeMetrics)

## Dealer Positioning Signals
- Dark pool DIX: Short-sale volume from dark pools → contrarian indicator
- GEX crossover: When GEX crosses zero → regime change signal
- Put/Call ratio: >1.0 extreme fear, <0.7 extreme greed
- VIX term structure: Backwardation = fear, contango = complacency
- 0DTE options: Same-day expiration flow drives intraday gamma dynamics

## Gamma Squeeze Mechanics
1. Retail buys OTM calls → dealers sell those calls
2. Dealers must delta-hedge by buying underlying
3. As price rises, delta increases → dealers buy more
4. Positive feedback loop → explosive rally
5. Unwind: When options expire or are sold → dealers sell underlying → sharp reversal

## Historical Gamma Events
- Jan 2021 GME: Retail call buying → largest gamma squeeze in history
- Aug 2024: Yen carry unwind + negative gamma → VIX spike to 65
- Mar 2020: COVID crash → extreme negative gamma → circuit breakers
- Feb 2018: Volmageddon → XIV collapse → vol regime change

## Trading Framework
- In positive gamma regime: Sell premium, mean-reversion strategies
- In negative gamma regime: Buy premium, trend-following, reduce size
- At gamma flip: Maximum uncertainty → reduce positions, wait for clarity
- Key levels: Major strike clusters (round numbers), max pain, zero gamma line
""",

    "sound_money": """# Sound Money & Hard Assets Reference

## Core Thesis
Fiat currencies are designed to lose purchasing power over time. Central banks systematically
debase their currencies through money printing, financial repression, and inflation targeting.
The only protection is to hold assets with natural scarcity: gold and Bitcoin.

## Gold as Money
- 5,000+ years as store of value — longest track record of any asset
- No counterparty risk — you own it outright
- Central banks are net buyers since 2010 (~1,000+ tonnes/year since 2022)
- Above-ground supply: ~210,000 tonnes, growing ~1.5%/year (natural inflation rate)
- Price drivers: real rates (inverted), dollar strength (inverted), central bank buying
- Fair value models: Shadow Gold Price = monetary base / gold reserves

## Bitcoin as Digital Gold
- Fixed supply: 21M coins, never more — hardest money ever created
- Stock-to-flow: ~120 (post-2024 halving) — more scarce than gold
- Network effect: Metcalfe's law → value grows as square of users
- Halving cycle: Supply shock every 4 years → historically 10-20x rallies within 18 months
- Energy thesis (Lyn Alden): Bitcoin converts stranded energy into monetary value
- Hash rate all-time highs → network security at peak

## Fiat Currency Debasement History
- Roman Denarius: 95% silver → 0.05% over 200 years
- British Pound: Lost 99.5% of purchasing power since 1900
- US Dollar: Lost 98% since Fed creation (1913)
- German Mark: Hyperinflation 1923 (1 trillion marks = 1 dollar)
- Zimbabwe Dollar: 79.6 billion % inflation (2008)
- Venezuelan Bolivar: 1,000,000% inflation (2018)

## Current Debasement Signals
- US national debt: $36T+ (120% debt/GDP)
- Interest on debt: exceeds defense spending
- Entitlement spending: Social Security/Medicare unfunded liabilities > $100T
- De-dollarization: BRICS nations settling in local currencies
- Central bank gold buying: Hedging against their own system
- Real interest rates: Often negative after inflation adjustment

## Investment Framework
- Core holdings: 50-70% gold + 20-40% Bitcoin (hard money portfolio)
- No bonds: Negative real returns = guaranteed loss of purchasing power
- No cash beyond 6 months expenses: Inflation tax = ~3-5%/year real loss
- Mining stocks: Leveraged play on gold (2-3x beta)
- Silver: Industrial + monetary demand → potential catch-up to gold
""",

    "permabear": """# Structural Bear Case — Market Cycle Analysis

## Current Concerns (2026)
- Shiller CAPE ratio: ~35x (top 3% historically, only exceeded by 1999-2000)
- Total market cap / GDP (Buffett Indicator): ~190% (all-time record territory)
- Household equity allocation: ~45% (highest since 2000 peak)
- Corporate debt/GDP: ~50% (near record)
- Private credit explosion: $1.5T+ opaque market with no price discovery
- Commercial real estate: Office vacancy >20%, $1.5T in refinancing needed

## Credit Cycle Warning Signs
- Yield curve inversion (2022-2024): Most reliable recession predictor
- Leading indicators: Conference Board LEI negative for 18+ months
- Bank lending standards: Tightening since 2022 → credit contraction ahead
- Credit card delinquencies: Rising to 2011 levels
- Auto loan delinquencies: Subprime 60+ day past due at record
- Student loan payments resumed → consumer spending headwind

## Historical Parallels
- 1929: Speculative mania → 89% drawdown → 25 years to recover
- 1973: Nifty Fifty → oil shock → 48% drawdown → stagflation decade
- 2000: Dot-com bubble → 78% Nasdaq drawdown → took 15 years
- 2007: Housing bubble → 57% drawdown → systemic crisis
- Common pattern: Euphoria → credit tightening → earnings miss → cascade

## Valuation Extremes
- Median stock P/E: ~22x (vs 15x historical median)
- Price/Sales: ~2.8x (vs 1.5x historical)
- EV/EBITDA: ~15x (vs 10x historical)
- Mag 7 concentration: ~30% of S&P 500 (most concentrated market since 1970s)
- Risk premium: equity risk premium near zero → stocks offer no premium over bonds

## Bear Market Anatomy
Phase 1: "Stealth" — Smart money exits, market makes lower highs
Phase 2: "Awareness" — First -20% drawdown, BTFD fails
Phase 3: "Panic" — Margin calls, forced selling, liquidity crisis
Phase 4: "Capitulation" — Everyone sells, VIX > 50, blood in streets
Phase 5: "Recovery" — Takes 3-10 years, new leadership emerges

## Catalysts That Could Trigger
1. Earnings recession (margins compressing from peak)
2. Credit event (private credit, CRE, or sovereign)
3. Geopolitical shock (Taiwan, Middle East escalation)
4. AI disillusionment (revenue fails to match capex)
5. Liquidity drain (QT + Treasury issuance > RRP drawdown)
6. Inflation re-acceleration (forces Fed to pause/hike)
""",

    "black_swan": """# Tail Risk & Convexity Framework

## Core Philosophy (Nassim Taleb)
- Markets are not normally distributed — fat tails are real
- Expected value of rare events is underpriced
- The Turkey Problem: Absence of evidence is not evidence of absence
- Barbell strategy: 85% ultra-safe + 15% ultra-aggressive (asymmetric payoff)
- Antifragility: Systems that gain from disorder

## Tail Risk Categories
### Financial System
- Sovereign debt default (Japan, Italy, US)
- Shadow banking collapse (private credit, money market breaks)
- SWIFT weaponization → parallel financial systems
- CBDC implementation → bank disintermediation
- Stablecoin de-peg cascade (Tether, USDC)

### Geopolitical
- Taiwan invasion → semiconductor supply shock (TSMC = 90% advanced chips)
- Nuclear escalation (Russia/Ukraine, North Korea, Iran)
- Gulf state regime change → oil supply disruption
- US constitutional crisis → institutional breakdown

### Technology
- AGI breakthrough → labor market disruption at scale
- AI-generated misinformation → societal trust collapse
- Cyber-warfare → critical infrastructure attack
- Quantum computing breaks RSA/ECC → all encryption compromised

### Natural / Pandemic
- Bird flu (H5N1) pandemic → 2020-style lockdowns
- Solar storm (Carrington-class) → electronics/grid failure
- Volcanic eruption → agricultural crisis → famine
- Antibiotic resistance → untreatable infections

## Convexity Strategies
- Long deep OTM puts (SPX, QQQ) — cheap insurance, massive payoff in crash
- Long VIX calls — profits when fear spikes
- Long gold + Bitcoin — hard assets during monetary crisis
- Long volatility (straddles on major events)
- Inverse ETFs (hedge, not core position)

## Position Sizing for Tail Risk
- Never risk more than you can afford to lose on any single tail bet
- Optionality: Pay small premium for unlimited upside
- Time decay is the cost of insurance — budget it like real insurance
- Roll positions: Don't hold to expiry, roll quarterly
- Size based on portfolio: 1-3% of portfolio in tail hedges

## Signals of Increasing Tail Risk
1. VIX term structure flattening/inverting
2. Credit spreads widening (IG > 150bps, HY > 500bps)
3. MOVE index > 150 (bond market stress)
4. TED spread widening (interbank trust breaking down)
5. Dollar milkshake: DXY rapid appreciation (global dollar shortage)
6. Repo rate spikes (overnight funding stress)
7. Gold + Bitcoin rising simultaneously (monetary crisis hedge)
""",

    "real_estate": """# Cabin Rentals of Georgia — Real Estate Intelligence

## CROG Operations Overview
Cabin Rentals of Georgia, LLC (CROG) operates a vacation rental property management company
in the North Georgia mountains, primarily serving the Blue Ridge and surrounding areas.

## Key Operational Metrics to Track
- Occupancy rate by property (target: 65-75% annual)
- Average Daily Rate (ADR) — seasonal adjustments critical
- RevPAR (Revenue Per Available Room) = Occupancy x ADR
- Guest satisfaction scores (Airbnb 4.8+, VRBO 4.5+)
- Maintenance cost per property per month
- Owner retention rate
- New property acquisition pipeline

## Seasonal Revenue Patterns (North Georgia)
- Peak: Oct-Nov (fall foliage), Jun-Aug (summer), Dec (holidays)
- Shoulder: Mar-May (spring), Sep (post-summer)
- Low: Jan-Feb (winter slow period)
- Strategy: Dynamic pricing — raise 30-50% during peak, discount 15-20% during low

## Market Intelligence
- North Georgia cabin rental market: $200M+ annual revenue
- Key competitors: Blue Ridge cabin rental companies, individual Airbnb hosts
- Differentiators: Full-service management, local knowledge, 24/7 guest support
- Trends: Remote work driving longer stays (5-7 nights vs 2-3 pre-2020)
- Threats: Regulation (county short-term rental ordinances), oversupply, economic downturn

## Property Management Best Practices
- Cleaning turnover: 4-hour window between guests
- Maintenance budget: 1-2% of property value annually
- Hot tub maintenance: Weekly chemical balance, quarterly drain/refill
- HVAC: Bi-annual service (spring/fall)
- Pest control: Quarterly exterior treatment
- Insurance: Require $1M liability, review annually

## Revenue Optimization Strategies
1. Dynamic pricing (PriceLabs, Wheelhouse, or Beyond Pricing)
2. Minimum night stays: 2-night weekdays, 3-night weekends, 4-night holidays
3. Pet-friendly premium: +$50-100/stay (60%+ of travelers have pets)
4. Early check-in / late checkout: +$50 upsell
5. Welcome packages: Local partnerships (wine, snacks) → 5-star reviews
6. Professional photography: 40% more bookings than amateur photos
7. Direct booking website: Save 12-15% platform fees

## Financial Framework
- Owner payout: 70-80% of gross revenue (after management fee)
- Management fee: 20-30% of gross
- Expense categories: Cleaning, maintenance, supplies, utilities, platform fees, insurance
- Capital improvements: Hot tub replacement ($8-15K), deck repair, appliance upgrades
- Tax considerations: Schedule E, depreciation, 1031 exchanges, cost segregation studies
""",
}


def ingest_seed_documents(slug: str, collection: str, state: Dict, dry_run: bool = False) -> int:
    """Ingest synthesized seed data for personas that have no external content yet."""
    if slug not in SEED_DOCUMENTS:
        return 0

    ingested_hashes = set(state.get("ingested", {}).get(slug, []))
    seed_hash = hashlib.sha256(f"seed:{slug}:v1".encode()).hexdigest()[:16]
    if seed_hash in ingested_hashes:
        log.info("  Seed data already ingested for %s", slug)
        return 0

    text = SEED_DOCUMENTS[slug]
    if dry_run:
        log.info("  [DRY] Would ingest seed document for %s (%d chars)", slug, len(text))
        return 1

    chunks = chunk_text(text, size=800, overlap=150)
    points = []
    for i, chunk in enumerate(chunks):
        emb = embed_text(chunk)
        if not emb:
            continue
        hx = hashlib.sha256(f"seed:{slug}:{i}".encode()).hexdigest()[:32]
        points.append({
            "id": str(uuid.UUID(hx)),
            "vector": emb,
            "payload": {
                "text": chunk,
                "source": "seed_document",
                "persona": slug,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "ingested_at": datetime.now().isoformat(),
            },
        })

    if points:
        uploaded = upload_points(collection, points)
        ingested_hashes.add(seed_hash)
        state.setdefault("ingested", {}).setdefault(slug, []).append(seed_hash)
        save_state(state)
        return uploaded
    return 0

# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status():
    """Print the status of all persona collections."""
    print()
    print("=" * 80)
    print("  FORTRESS PRIME — COUNCIL OF GIANTS — STATUS REPORT")
    print("=" * 80)
    print()

    state = load_state()
    total_vectors = 0

    for slug in sorted(SLUG_TO_DIR.keys()):
        collection = f"{slug}_intel"
        try:
            r = requests.get(
                f"{QDRANT_URL}/collections/{collection}",
                headers={"api-key": QDRANT_API_KEY},
                timeout=5,
            )
            if r.status_code == 200:
                count = r.json().get("result", {}).get("points_count", 0)
            else:
                count = "N/A"
        except Exception:
            count = "ERR"

        persona_file = PERSONAS_DIR / f"{slug}.json"
        if persona_file.exists():
            pdata = json.loads(persona_file.read_text())
            name = pdata.get("name", slug)
            archetype = pdata.get("archetype", "?")
        else:
            name = slug
            archetype = "?"

        ingested_count = len(state.get("ingested", {}).get(slug, []))
        nas_dir = INTEL_BASE / SLUG_TO_DIR.get(slug, slug)
        nas_files = sum(1 for _ in nas_dir.rglob("*") if _.is_file() and _.suffix.lower() in INGEST_EXTS) if nas_dir.exists() else 0

        vectors_display = str(count) if isinstance(count, int) else count
        if isinstance(count, int):
            total_vectors += count
        status = "ACTIVE" if isinstance(count, int) and count > 0 else "EMPTY"

        print(f"  {name:22s} │ {archetype:20s} │ {vectors_display:>8s} vectors │ {nas_files:3d} NAS │ {status}")

    print()
    print(f"  Total vectors across all personas: {total_vectors:,}")
    print()

    # Data source status
    fred_key = "SET" if os.getenv("FRED_API_KEY") else "NOT SET"
    xai_key = "SET" if os.getenv("XAI_API_KEY") else "NOT SET"
    yt_key = "SET" if os.getenv("YOUTUBE_API_KEY") else "N/A (yt-dlp)"
    print("  Data Sources:")
    print(f"    NAS local files     : /mnt/fortress_nas/Intelligence/")
    print(f"    Project docs        : {PROJECT_ROOT}/docs/")
    print(f"    RSS/Atom feeds      : {len(PERSONA_FEEDS)} personas configured")
    print(f"    FRED economic data  : FRED_API_KEY={fred_key}")
    print(f"    Twitter/X (xAI)     : XAI_API_KEY={xai_key}")
    print(f"    YouTube transcripts : yt-dlp ({yt_key})")
    print()
    print("=" * 80)
    print()

# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def process_persona(slug: str, state: Dict, dry_run: bool = False, source_filter: str = None) -> Dict:
    """Process all sources for one persona. Returns stats dict."""
    collection = f"{slug}_intel"
    stats = {"slug": slug, "local": 0, "docs": 0, "seed": 0, "fred": 0, "rss": 0, "x": 0, "youtube": 0}

    log.info("Processing: %s → %s", slug, collection)

    # 1. Local NAS files
    if not source_filter or source_filter == "local":
        stats["local"] = ingest_local_files(slug, collection, state, dry_run)

    # 2. Project docs (keyword-matched)
    if not source_filter or source_filter == "docs":
        stats["docs"] = ingest_project_docs(slug, collection, state, dry_run)

    # 3. Seed documents (synthesized reference data)
    if not source_filter or source_filter == "seed":
        stats["seed"] = ingest_seed_documents(slug, collection, state, dry_run)

    # 4. FRED data (fed_watcher only)
    if slug == "fed_watcher" and (not source_filter or source_filter == "fred"):
        stats["fred"] = fetch_fred_data(state, dry_run)

    # 5. RSS/Substack feeds
    if not source_filter or source_filter == "rss":
        stats["rss"] = fetch_rss_content(slug, collection, state, dry_run)

    # 6. Twitter/X via xAI Grok API
    if not source_filter or source_filter == "x":
        stats["x"] = fetch_x_content(slug, collection, state, dry_run)

    # 7. YouTube transcripts via yt-dlp
    if not source_filter or source_filter == "youtube":
        stats["youtube"] = fetch_youtube_transcripts(slug, collection, state, dry_run)

    numeric = {k: v for k, v in stats.items() if isinstance(v, int)}
    total = sum(numeric.values())
    log.info("  %s total: %d vectors (local=%d, docs=%d, seed=%d, fred=%d, rss=%d, x=%d, yt=%d)",
             slug, total, stats["local"], stats["docs"],
             stats["seed"], stats["fred"], stats["rss"],
             stats["x"], stats["youtube"])
    return stats

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Universal Intelligence Hunter — ingest content for all Council personas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--persona", help="Single persona slug (jordi, raoul, lyn, etc.)")
    parser.add_argument("--all", action="store_true", help="Process all 9 personas")
    parser.add_argument("--source", choices=["local", "docs", "seed", "fred", "rss", "x", "youtube"],
                        help="Only process this source type")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested")
    parser.add_argument("--status", action="store_true", help="Print status report")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    if not args.persona and not args.all:
        parser.print_help()
        print("\nExamples:")
        print("  python src/universal_intelligence_hunter.py --status")
        print("  python src/universal_intelligence_hunter.py --all")
        print("  python src/universal_intelligence_hunter.py --persona fed_watcher --source fred")
        print("  python src/universal_intelligence_hunter.py --all --dry-run")
        return

    state = load_state()
    slugs = sorted(SLUG_TO_DIR.keys()) if args.all else [args.persona]

    print()
    print("=" * 72)
    mode = "DRY RUN" if args.dry_run else "LIVE INGESTION"
    print(f"  UNIVERSAL INTELLIGENCE HUNTER — {mode}")
    print(f"  Personas: {', '.join(slugs)}")
    if args.source:
        print(f"  Source filter: {args.source}")
    print("=" * 72)
    print()

    grand_total = 0
    for slug in slugs:
        stats = process_persona(slug, state, dry_run=args.dry_run, source_filter=args.source)
        grand_total += sum(v for v in stats.values() if isinstance(v, int))
        print()

    print("=" * 72)
    print(f"  GRAND TOTAL: {grand_total} vectors ingested across {len(slugs)} personas")
    print("=" * 72)

    if not args.dry_run:
        print("\nRun --status to see updated collection counts.")


if __name__ == "__main__":
    main()
