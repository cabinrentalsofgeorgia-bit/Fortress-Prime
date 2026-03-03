#!/usr/bin/env python3
"""
Fortress Vault Ingestion Engine — Multi-Domain Resumable Pipeline
=================================================================
Routes files from /tmp/dqa_missing.json into domain-specific Qdrant
collections using the 4-GPU Ollama cluster for parallel embedding.

Domain routing:
  .pdf / .doc / .docx  →  fortress_knowledge  (general) or legal_library (legal path)
  .json (MarketClub)   →  market_intelligence  (structured metadata payload)
  .emlx                →  email_embeddings     (queued, not run by default)

State tracking via SQLite (tools/.vault_ingest_state.db) for crash-safe resumption.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_ollama_endpoints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vault_ingest")

# ── Configuration ─────────────────────────────────────────────────
EMBED_NODES = get_ollama_endpoints()
EMBED_MODEL = "nomic-embed-text"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
STATE_DB = os.path.join(os.path.dirname(__file__), ".vault_ingest_state.db")
MISSING_MANIFEST = "/tmp/dqa_missing.json"

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 300
MAX_FILE_SIZE = 50_000_000  # 50 MB

QDRANT_BATCH = 15
QDRANT_SUB_BATCH = 15  # max points per HTTP upsert to stay under 32MB gRPC limit
WORKERS_PER_NODE = 6

MARKETCLUB_PATH_PATTERN = re.compile(r"Business_MarketClub", re.IGNORECASE)
LEGAL_PATH_PATTERN = re.compile(
    r"(sectors/legal|Legal|legal_library|court|litigation|case[-_])",
    re.IGNORECASE,
)

# ── State DB ──────────────────────────────────────────────────────

def init_state_db() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingested_files (
            file_path   TEXT PRIMARY KEY,
            collection  TEXT NOT NULL,
            chunks      INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'done',
            ingested_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def is_already_ingested(conn: sqlite3.Connection, path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ingested_files WHERE file_path = ? AND status = 'done'",
        (path,),
    ).fetchone()
    return row is not None


def mark_ingested(
    conn: sqlite3.Connection, path: str, collection: str, chunks: int
):
    conn.execute(
        """INSERT OR REPLACE INTO ingested_files
           (file_path, collection, chunks, status, ingested_at)
           VALUES (?, ?, ?, 'done', datetime('now'))""",
        (path, collection, chunks),
    )
    conn.commit()


# ── Text Extraction ───────────────────────────────────────────────

def extract_pdf(path: str) -> str:
    try:
        import pdfplumber

        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return "\n".join(texts)
    except Exception:
        return ""


def extract_docx(path: str) -> str:
    try:
        import docx

        doc = docx.Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    elif ext in (".doc", ".docx"):
        return extract_docx(path)
    elif ext in (".txt", ".md", ".csv", ".html", ".rtf"):
        try:
            with open(path, "r", errors="replace") as f:
                return f.read(MAX_FILE_SIZE)
        except Exception:
            return ""
    return ""


def chunk_text(text: str) -> List[str]:
    if len(text) <= CHUNK_SIZE:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── MarketClub JSON Parser ────────────────────────────────────────

def parse_marketclub_json(path: str) -> Optional[Dict]:
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return None

    meta = data if isinstance(data, dict) else {}
    subject = meta.get("subject", "")
    body = meta.get("body_text", meta.get("body", ""))

    ticker_match = re.search(r"\b([A-Z]{1,5})\b", subject)
    ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"

    exchange = "NYSE"
    if any(x in subject.upper() for x in ["FOREX", "EUR", "GBP", "JPY"]):
        exchange = "FOREX"
    elif any(x in subject.upper() for x in ["CRYPTO", "BTC", "ETH"]):
        exchange = "CRYPTO"

    signal_color = "neutral"
    if "green" in subject.lower() or "bullish" in body.lower():
        signal_color = "green"
    elif "red" in subject.lower() or "bearish" in body.lower():
        signal_color = "red"

    signal_timeframe = "daily"
    if "weekly" in subject.lower() or "weekly" in body.lower():
        signal_timeframe = "weekly"
    elif "monthly" in subject.lower():
        signal_timeframe = "monthly"

    score_match = re.search(r"Score[:\s]*([+-]?\d+)", body)
    score = int(score_match.group(1)) if score_match else 0

    price_match = re.search(r"\$?([\d,]+\.?\d*)", body)
    price = float(price_match.group(1).replace(",", "")) if price_match else 0.0

    net_match = re.search(r"Net[:\s]*([+-]?[\d.]+)", body)
    net_change = float(net_match.group(1)) if net_match else 0.0

    pct_match = re.search(r"([+-]?[\d.]+)%", body)
    pct_change = float(pct_match.group(1)) if pct_match else 0.0

    timestamp = meta.get("date", meta.get("timestamp", ""))

    embed_text = f"{ticker} {exchange} {signal_color} signal ({signal_timeframe}). Score: {score}. Price: {price}. {subject}"

    payload = {
        "ticker": ticker,
        "exchange": exchange,
        "signal_color": signal_color,
        "signal_timeframe": signal_timeframe,
        "score": score,
        "price": price,
        "net_change": net_change,
        "pct_change": pct_change,
        "timestamp_utc": timestamp,
        "subject": subject,
        "source_file": path,
        "alert_id": meta.get("id", ""),
        "ingest_timestamp": meta.get("ingest_timestamp", ""),
    }

    return {"embed_text": embed_text, "payload": payload}


# ── Embedding (with circuit breaker) ─────────────────────────────

_node_idx = 0
_node_failures: Dict[str, int] = {}
_node_tripped_until: Dict[str, float] = {}
_CB_THRESHOLD = 5          # consecutive failures before tripping
_CB_COOLDOWN_SEC = 60      # seconds to skip a tripped node

_embed_session = requests.Session()
_embed_adapter = requests.adapters.HTTPAdapter(
    pool_connections=len(EMBED_NODES),
    pool_maxsize=256,
    max_retries=0,
)
_embed_session.mount("http://", _embed_adapter)


def _is_node_healthy(node: str) -> bool:
    now = time.monotonic()
    tripped = _node_tripped_until.get(node, 0)
    if now < tripped:
        return False
    if now >= tripped and tripped > 0:
        _node_tripped_until.pop(node, None)
        _node_failures[node] = 0
    return True


def _record_failure(node: str):
    _node_failures[node] = _node_failures.get(node, 0) + 1
    if _node_failures[node] >= _CB_THRESHOLD:
        _node_tripped_until[node] = time.monotonic() + _CB_COOLDOWN_SEC
        log.warning(
            "CIRCUIT BREAKER OPEN: %s tripped after %d consecutive failures. "
            "Bypassing for %ds.",
            node, _node_failures[node], _CB_COOLDOWN_SEC,
        )


def _record_success(node: str):
    _node_failures[node] = 0
    _node_tripped_until.pop(node, None)


def _next_healthy_node() -> Optional[str]:
    global _node_idx
    n = len(EMBED_NODES)
    for _ in range(n):
        node = EMBED_NODES[_node_idx % n]
        _node_idx += 1
        if _is_node_healthy(node):
            return node
    return None


def get_embedding(text: str, retries: int = 3) -> Optional[List[float]]:
    for attempt in range(retries):
        node = _next_healthy_node()
        if not node:
            log.error("ALL embed nodes tripped. Waiting %ds for cooldown.", _CB_COOLDOWN_SEC)
            time.sleep(_CB_COOLDOWN_SEC)
            node = _next_healthy_node()
            if not node:
                return None
        try:
            resp = _embed_session.post(
                f"{node}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
                timeout=10,
            )
            if resp.status_code == 200:
                emb = resp.json().get("embedding")
                if emb and len(emb) == 768:
                    _record_success(node)
                    return emb
            log.warning(
                "Embed node %s returned %d on attempt %d",
                node, resp.status_code, attempt + 1,
            )
            _record_failure(node)
        except requests.exceptions.Timeout:
            log.warning("Embed node %s TIMEOUT (10s) on attempt %d", node, attempt + 1)
            _record_failure(node)
        except requests.exceptions.ConnectionError:
            log.warning("Embed node %s CONNECTION REFUSED on attempt %d", node, attempt + 1)
            _record_failure(node)
        except Exception as e:
            log.warning("Embed node %s error on attempt %d: %s", node, attempt + 1, e)
            _record_failure(node)
        time.sleep(0.3 * (attempt + 1))
    return None


# ── Qdrant Upsert ─────────────────────────────────────────────────

def _qdrant_upsert_raw(collection: str, points: List[Dict]) -> bool:
    """Low-level upsert. Returns True on success."""
    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{collection}/points",
            json={"points": points},
            timeout=60,
            params={"wait": "true"},
        )
        if resp.status_code in (200, 201):
            return True
        log.error("Qdrant upsert failed (%s, %d pts): %s", collection, len(points), resp.text[:300])
        return False
    except requests.exceptions.Timeout:
        log.error("Qdrant upsert TIMEOUT (60s) for %s (%d pts)", collection, len(points))
        return False
    except requests.exceptions.ConnectionError:
        log.error("Qdrant CONNECTION REFUSED for %s (%d pts)", collection, len(points))
        return False
    except Exception as e:
        log.error("Qdrant upsert exception for %s: %s", collection, e)
        return False


def qdrant_upsert(collection: str, points: List[Dict]):
    """Sub-batched upsert -- splits large point lists into QDRANT_SUB_BATCH
    sized chunks so we never breach the 32MB payload limit.  If a sub-batch
    still fails, falls back to single-point upsert as a last resort."""
    if not points:
        return
    for i in range(0, len(points), QDRANT_SUB_BATCH):
        chunk = points[i : i + QDRANT_SUB_BATCH]
        if not _qdrant_upsert_raw(collection, chunk):
            log.warning(
                "Sub-batch failed for %s (%d pts at offset %d), falling back to single-point",
                collection, len(chunk), i,
            )
            for pt in chunk:
                _qdrant_upsert_raw(collection, [pt])


# ── Domain Router ─────────────────────────────────────────────────

def route_file(path: str) -> Optional[str]:
    """Determine target collection based on path and extension."""
    ext = Path(path).suffix.lower()

    if ext == ".json" and MARKETCLUB_PATH_PATTERN.search(path):
        return "market_intelligence"

    if ext == ".emlx":
        return "email_embeddings"

    if ext in (".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".html", ".rtf"):
        if LEGAL_PATH_PATTERN.search(path):
            return "legal_library"
        return "fortress_knowledge"

    return None


# ── Per-File Processors ───────────────────────────────────────────

def process_document(path: str, collection: str) -> List[Dict]:
    """Extract text, chunk, embed, return Qdrant points."""
    text = extract_text(path)
    if not text or len(text.strip()) < 50:
        return []

    chunks = chunk_text(text)
    points = []
    for i, chunk in enumerate(chunks):
        emb = get_embedding(chunk)
        if not emb:
            continue
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}#chunk{i}"))
        points.append({
            "id": point_id,
            "vector": emb,
            "payload": {
                "text": chunk,
                "source_file": path,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "file_type": Path(path).suffix.lower(),
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            },
        })
    return points


def process_marketclub(path: str) -> List[Dict]:
    """Parse JSON, embed summary, return Qdrant point with structured payload."""
    parsed = parse_marketclub_json(path)
    if not parsed:
        return []

    emb = get_embedding(parsed["embed_text"])
    if not emb:
        return []

    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, path))
    return [{
        "id": point_id,
        "vector": emb,
        "payload": parsed["payload"],
    }]


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace. No external dependency."""
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:p|div|h[1-6]|li|tr|td|th|blockquote)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_emlx_rfc822(raw_bytes: bytes) -> bytes:
    """EMLX format: first line is byte-count, then RFC-822 message,
    then an Apple plist trailer.  Return just the RFC-822 portion."""
    first_nl = raw_bytes.find(b"\n")
    if first_nl < 0:
        return raw_bytes
    maybe_count = raw_bytes[:first_nl].strip()
    if maybe_count.isdigit():
        byte_count = int(maybe_count)
        return raw_bytes[first_nl + 1 : first_nl + 1 + byte_count]
    return raw_bytes


def _extract_text_from_mime(msg) -> str:
    """Walk the MIME tree.  Keep ONLY text/plain and text/html parts.
    Completely ignore attachments, images, Base64 binary payloads."""
    from email import policy

    text_parts: List[str] = []
    html_parts: List[str] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition.lower():
            continue

        if content_type == "text/plain":
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    text_parts.append(payload.decode(charset, errors="replace"))
            except Exception:
                pass

        elif content_type == "text/html":
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    html_parts.append(_strip_html(payload.decode(charset, errors="replace")))
            except Exception:
                pass

    if text_parts:
        return "\n\n".join(text_parts)
    if html_parts:
        return "\n\n".join(html_parts)
    return ""


def process_emlx(path: str) -> List[Dict]:
    """Parse Apple Mail .emlx with proper MIME handling.
    Extracts ONLY text/plain and text/html payloads.
    Completely ignores Base64 attachments, images, videos, and binary parts."""
    from email import message_from_bytes

    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_SIZE)
    except Exception:
        return []

    rfc822_bytes = _extract_emlx_rfc822(raw)
    try:
        msg = message_from_bytes(rfc822_bytes)
    except Exception:
        return []

    subject = str(msg.get("Subject", ""))
    from_addr = str(msg.get("From", ""))
    date_str = str(msg.get("Date", ""))

    body_text = _extract_text_from_mime(msg)

    if len(body_text.strip()) < 30:
        return []

    chunks = chunk_text(body_text)
    if not chunks:
        return []

    points = []
    for i, chunk in enumerate(chunks):
        emb = get_embedding(chunk)
        if not emb:
            continue
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}#chunk{i}"))
        points.append({
            "id": point_id,
            "vector": emb,
            "payload": {
                "preview": chunk[:500],
                "body": chunk,
                "subject": subject,
                "from": from_addr,
                "date": date_str,
                "source_file": path,
                "chunk_index": i,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            },
        })
    return points


# ── Main Ingestion Loop ───────────────────────────────────────────

def load_manifest(
    tier: str = "tier1",
) -> List[Tuple[str, str]]:
    """Load missing files and filter by tier. Returns (path, collection) tuples."""
    with open(MISSING_MANIFEST) as f:
        data = json.load(f)

    files = data.get("missing", data if isinstance(data, list) else [])
    routed: List[Tuple[str, str]] = []

    for fp in files:
        collection = route_file(fp)
        if not collection:
            continue

        if tier == "tier1":
            ext = Path(fp).suffix.lower()
            if ext == ".emlx":
                continue
            routed.append((fp, collection))
        elif tier == "emlx":
            if Path(fp).suffix.lower() == ".emlx":
                routed.append((fp, collection))
        else:
            routed.append((fp, collection))

    return routed


def process_file(
    path: str, collection: str
) -> Tuple[str, str, int, List[Dict]]:
    """Process a single file and return (path, collection, chunk_count, points)."""
    if not os.path.exists(path):
        return (path, collection, 0, [])

    if os.path.getsize(path) > MAX_FILE_SIZE:
        return (path, collection, 0, [])

    if collection == "market_intelligence":
        points = process_marketclub(path)
    elif collection == "email_embeddings":
        points = process_emlx(path)
    else:
        points = process_document(path, collection)

    return (path, collection, len(points), points)


def run_ingestion(tier: str = "tier1"):
    log.info("=== Fortress Vault Ingestion Engine ===")
    log.info("Tier: %s | Embed nodes: %d | Workers: %d", tier, len(EMBED_NODES), len(EMBED_NODES) * WORKERS_PER_NODE)

    conn = init_state_db()
    manifest = load_manifest(tier)
    log.info("Manifest loaded: %d files", len(manifest))

    pending = [(p, c) for p, c in manifest if not is_already_ingested(conn, p)]
    log.info("After resume filter: %d files to process", len(pending))

    if not pending:
        log.info("Nothing to ingest. All files already processed.")
        return

    stats = {
        "processed": 0,
        "skipped": 0,
        "chunks_total": 0,
        "errors": 0,
        "by_collection": {},
    }
    qdrant_buffer: Dict[str, List[Dict]] = {}
    start_time = time.time()

    def flush_buffer(collection: str):
        if collection in qdrant_buffer and qdrant_buffer[collection]:
            qdrant_upsert(collection, qdrant_buffer[collection])
            qdrant_buffer[collection] = []

    max_workers = len(EMBED_NODES) * WORKERS_PER_NODE
    window = max_workers * 2  # sliding window: keep 2x workers in flight
    pending_iter = iter(pending)
    total_pending = len(pending)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        live: Dict = {}
        for _ in range(window):
            try:
                path, coll = next(pending_iter)
                fut = pool.submit(process_file, path, coll)
                live[fut] = (path, coll)
            except StopIteration:
                break

        while live:
            done_set = {f for f in live if f.done()}
            if not done_set:
                time.sleep(0.05)
                continue

            for future in done_set:
                path, coll = live.pop(future)
                try:
                    _, collection, chunk_count, points = future.result()
                except Exception as e:
                    log.warning("Worker error on %s: %s", path, e)
                    stats["errors"] += 1
                    try:
                        np, nc = next(pending_iter)
                        live[pool.submit(process_file, np, nc)] = (np, nc)
                    except StopIteration:
                        pass
                    continue

                if not points:
                    stats["skipped"] += 1
                    mark_ingested(conn, path, collection, 0)
                else:
                    stats["processed"] += 1
                    stats["chunks_total"] += chunk_count
                    stats["by_collection"][collection] = (
                        stats["by_collection"].get(collection, 0) + chunk_count
                    )

                    if collection not in qdrant_buffer:
                        qdrant_buffer[collection] = []
                    qdrant_buffer[collection].extend(points)

                    if len(qdrant_buffer[collection]) >= QDRANT_BATCH:
                        flush_buffer(collection)

                    mark_ingested(conn, path, collection, chunk_count)

                total_done = stats["processed"] + stats["skipped"]
                if total_done % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = total_done / elapsed if elapsed > 0 else 0
                    log.info(
                        "Progress: %d/%d (%.1f files/sec) | chunks=%d | errors=%d",
                        total_done,
                        total_pending,
                        rate,
                        stats["chunks_total"],
                        stats["errors"],
                    )

                try:
                    np, nc = next(pending_iter)
                    live[pool.submit(process_file, np, nc)] = (np, nc)
                except StopIteration:
                    pass

    for coll in qdrant_buffer:
        flush_buffer(coll)

    elapsed = time.time() - start_time
    conn.close()

    log.info("=== INGESTION COMPLETE ===")
    log.info("Total time: %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)
    log.info("Files processed: %d", stats["processed"])
    log.info("Files skipped (empty/missing): %d", stats["skipped"])
    log.info("Total chunks upserted: %d", stats["chunks_total"])
    log.info("Errors: %d", stats["errors"])
    log.info("-- Collection Distribution --")
    for coll, cnt in sorted(stats["by_collection"].items()):
        log.info("  %s: %d chunks", coll, cnt)


if __name__ == "__main__":
    tier = sys.argv[1] if len(sys.argv) > 1 else "tier1"
    run_ingestion(tier)
