#!/usr/bin/env python3
"""
FORTRESS SENTINEL — Continuous Document Indexing Daemon
========================================================
Watches all NAS + project directories for new/modified files.
Embeds them into Qdrant `fortress_knowledge` using the same pipeline
as total_recall_turbo.py (4-GPU parallel embedding).

Runs as a persistent service. Designed to never stop.

Architecture:
  1. SCAN:  Every SCAN_INTERVAL seconds, crawl all watched directories
  2. DIFF:  Compare against known ingested files in Qdrant
  3. EMBED: Process new/modified files through 4-GPU embedding pipeline
  4. SLEEP: Wait for next scan cycle

Handles:
  - New files appearing on NAS (drag-and-drop, rsync, scripts)
  - Modified files (re-indexed if mtime changed since last ingest)
  - Project code changes (re-indexed automatically)
  - Graceful shutdown on SIGTERM/SIGINT

Usage:
  # Start as daemon
  python tools/fortress_sentinel.py

  # One-shot scan (check for new files, ingest, exit)
  python tools/fortress_sentinel.py --once

  # Custom scan interval (default 120s)
  python tools/fortress_sentinel.py --interval 60
"""

import os
import sys
import time
import json
import signal
import hashlib
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get_ollama_endpoints, MUSCLE_EMBED_MODEL

# ─── Configuration ────────────────────────────────────────────────

EMBED_NODES = get_ollama_endpoints()
EMBED_MODEL = MUSCLE_EMBED_MODEL
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
COLLECTION = "fortress_knowledge"

SCAN_INTERVAL = int(os.getenv("SENTINEL_INTERVAL", "120"))  # seconds

# Watched directories
WATCH_DIRS = [
    # NAS directories
    "/mnt/fortress_nas/Business_Prime",
    "/mnt/fortress_nas/Corporate_Legal",
    "/mnt/fortress_nas/Financial_Ledger",
    "/mnt/fortress_nas/Real_Estate_Assets",
    "/mnt/fortress_nas/Enterprise_War_Room",
    "/mnt/fortress_nas/Communications",
    "/mnt/fortress_nas/sectors",
    # Project directory
    "/home/admin/Fortress-Prime",
]

EXTENSIONS = {
    ".pdf", ".txt", ".md", ".csv", ".html", ".eml", ".emlx",
    ".py", ".sh", ".sql", ".yaml", ".yml", ".json",
    ".doc", ".docx", ".rtf",
}
SKIP_DIRS = {
    "__pycache__", ".git", ".cursor", "node_modules", "venv",
    ".venv", "#recycle", "@eaDir", "chroma_db", "nim_cache",
    "models", "titan_engine", "raw_images", ".tox", "dist",
    "build", ".eggs", "open-webui-data",
}
SKIP_FILES = {".env", "credentials", ".key", ".pem", ".p12"}

MAX_CHARS = 2000       # chars per chunk (~500 tokens)
OVERLAP_CHARS = 400    # overlap between chunks
MAX_FILE_SIZE = 50_000_000  # 50MB
QDRANT_BATCH = 100     # vectors per upsert

# State file: tracks mtime of ingested files for change detection
STATE_FILE = os.path.expanduser("~/.fortress_sentinel_state.json")

# ─── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SENTINEL] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sentinel")

# ─── Graceful Shutdown ────────────────────────────────────────────

_shutdown = threading.Event()


def _handle_signal(signum, frame):
    log.info(f"Received signal {signum}, shutting down gracefully...")
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ─── Text Extraction ─────────────────────────────────────────────

def extract_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        return ""


def extract_file(path: str) -> str:
    if Path(path).suffix.lower() == ".pdf":
        return extract_pdf(path)
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


# ─── Chunking ─────────────────────────────────────────────────────

def chunk_text(text: str, source: str) -> list[dict]:
    text = text.replace("\x00", "").strip()
    if len(text) < 50:
        return []

    chunks = []
    idx = 0
    chunk_num = 0
    while idx < len(text):
        end = min(idx + MAX_CHARS, len(text))
        chunk = text[idx:end]

        if end < len(text):
            last_break = chunk.rfind("\n\n")
            if last_break > MAX_CHARS // 2:
                chunk = chunk[:last_break]
                end = idx + last_break
            else:
                last_period = chunk.rfind(". ")
                if last_period > MAX_CHARS // 2:
                    chunk = chunk[:last_period + 1]
                    end = idx + last_period + 1

        chunk = chunk.strip()
        if len(chunk) > 50:
            chunk_num += 1
            chunks.append({
                "text": chunk,
                "source": source,
                "chunk_num": chunk_num,
                "char_offset": idx,
            })

        idx = end - OVERLAP_CHARS if end < len(text) else len(text)

    return chunks


# ─── File Discovery ───────────────────────────────────────────────

def crawl_all() -> dict[str, float]:
    """Returns {filepath: mtime} for all eligible files."""
    files = {}
    for root_dir in WATCH_DIRS:
        if not os.path.exists(root_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                if any(s in fname.lower() for s in SKIP_FILES):
                    continue
                fpath = os.path.join(dirpath, fname)
                ext = Path(fpath).suffix.lower()
                if ext not in EXTENSIONS:
                    continue
                try:
                    stat = os.stat(fpath)
                    if stat.st_size < 50 or stat.st_size > MAX_FILE_SIZE:
                        continue
                    files[fpath] = stat.st_mtime
                except OSError:
                    continue
    return files


# ─── State Management ─────────────────────────────────────────────

def load_state() -> dict[str, float]:
    """Load the last-known mtime for each ingested file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict[str, float]):
    """Persist the state file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        log.warning(f"Failed to save state: {e}")


def init_state_from_qdrant() -> dict[str, float]:
    """Bootstrap state from Qdrant if no state file exists.
    Marks all currently-ingested files as 'known' so we don't re-ingest."""
    log.info("Bootstrapping state from Qdrant (first run)...")
    state = {}
    try:
        offset = None
        seen = 0
        while True:
            body = {
                "limit": 100,
                "with_payload": {"include": ["source_file"]},
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            resp = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                json=body, headers=QDRANT_HEADERS, timeout=30,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            for p in result.get("points", []):
                sf = p.get("payload", {}).get("source_file", "")
                if sf and sf not in state:
                    # Use current mtime if file exists, else 0
                    try:
                        state[sf] = os.path.getmtime(sf)
                    except OSError:
                        state[sf] = 0
                    seen += 1

            offset = result.get("next_page_offset")
            if offset is None:
                break

        log.info(f"Bootstrapped state: {seen:,} unique files from Qdrant")
    except Exception as e:
        log.warning(f"Failed to bootstrap from Qdrant: {e}")

    save_state(state)
    return state


# ─── Embedding Engine ─────────────────────────────────────────────

class SentinelEmbedder:
    """Round-robin embedding across GPU nodes."""

    def __init__(self):
        self._node_idx = 0
        self._lock = threading.Lock()

    def _next_node(self) -> str:
        with self._lock:
            url = EMBED_NODES[self._node_idx]
            self._node_idx = (self._node_idx + 1) % len(EMBED_NODES)
            return url

    def embed(self, text: str) -> list:
        node = self._next_node()
        resp = requests.post(
            f"{node}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])

    def delete_file_vectors(self, source_file: str):
        """Remove existing vectors for a file (before re-indexing)."""
        try:
            requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
                json={
                    "filter": {
                        "must": [
                            {"key": "source_file", "match": {"value": source_file}}
                        ]
                    }
                },
                timeout=30,
            )
        except Exception as e:
            log.warning(f"Failed to delete old vectors for {source_file}: {e}")

    def ingest_file(self, fpath: str, is_update: bool = False) -> int:
        """Extract, chunk, embed, and store a single file. Returns vector count."""
        try:
            text = extract_file(fpath)
            if not text or len(text.strip()) < 50:
                return 0

            chunks = chunk_text(text, fpath)
            if not chunks:
                return 0

            # If updating, remove old vectors first
            if is_update:
                self.delete_file_vectors(fpath)

            # Embed and store in batches
            points = []
            for chunk in chunks:
                try:
                    vec = self.embed(chunk["text"])
                    if not vec:
                        continue

                    point_id = hashlib.md5(
                        f"{fpath}:{chunk['chunk_num']}:{chunk['char_offset']}".encode()
                    ).hexdigest()

                    points.append({
                        "id": point_id,
                        "vector": vec,
                        "payload": {
                            "source_file": fpath,
                            "chunk_num": chunk["chunk_num"],
                            "char_offset": chunk["char_offset"],
                            "text": chunk["text"][:500],
                            "file_type": Path(fpath).suffix.lower(),
                            "ingested_at": datetime.now().isoformat(),
                        },
                    })

                    if len(points) >= QDRANT_BATCH:
                        self._upsert(points)
                        points = []

                except Exception as e:
                    log.debug(f"Embed error for chunk in {fpath}: {e}")

            if points:
                self._upsert(points)

            return len(chunks)

        except Exception as e:
            log.warning(f"Failed to ingest {fpath}: {e}")
            return 0

    def _upsert(self, points: list):
        requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json={"points": points},
            headers=QDRANT_HEADERS,
            timeout=60,
        ).raise_for_status()


# ─── Main Loop ────────────────────────────────────────────────────

def run_scan(state: dict, embedder: SentinelEmbedder) -> dict:
    """Run a single scan cycle. Returns updated state."""
    log.info("Scanning for new/modified files...")
    current_files = crawl_all()

    # Find new and modified files
    new_files = []
    modified_files = []
    for fpath, mtime in current_files.items():
        if fpath not in state:
            new_files.append(fpath)
        elif mtime > state.get(fpath, 0):
            modified_files.append(fpath)

    if not new_files and not modified_files:
        log.info(f"No changes detected. ({len(current_files):,} files, {len(state):,} indexed)")
        return state

    log.info(f"Found {len(new_files)} new + {len(modified_files)} modified files")

    # Process new files
    total_vectors = 0
    processed = 0
    for fpath in new_files:
        if _shutdown.is_set():
            break
        vec_count = embedder.ingest_file(fpath, is_update=False)
        if vec_count > 0:
            state[fpath] = current_files[fpath]
            total_vectors += vec_count
            processed += 1
        if processed % 50 == 0 and processed > 0:
            log.info(f"  Progress: {processed}/{len(new_files)} new files, {total_vectors} vectors")
            save_state(state)  # Checkpoint

    # Process modified files
    for fpath in modified_files:
        if _shutdown.is_set():
            break
        vec_count = embedder.ingest_file(fpath, is_update=True)
        if vec_count > 0:
            state[fpath] = current_files[fpath]
            total_vectors += vec_count
            processed += 1

    save_state(state)
    log.info(f"Scan complete: {processed} files ingested, {total_vectors} vectors added/updated")
    return state


def main():
    parser = argparse.ArgumentParser(description="Fortress Sentinel — Continuous Indexing")
    parser.add_argument("--once", action="store_true", help="Single scan, then exit")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL, help="Scan interval in seconds")
    parser.add_argument("--reset-state", action="store_true", help="Reset state and re-bootstrap from Qdrant")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("  FORTRESS SENTINEL — Continuous Document Indexing")
    log.info("=" * 60)
    log.info(f"  Watch dirs:   {len(WATCH_DIRS)}")
    log.info(f"  GPU nodes:    {len(EMBED_NODES)}")
    log.info(f"  Qdrant:       {QDRANT_URL}/collections/{COLLECTION}")
    log.info(f"  Scan interval: {args.interval}s")
    log.info(f"  Mode:         {'one-shot' if args.once else 'continuous'}")
    log.info("=" * 60)

    # Verify Qdrant collection exists
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", headers=QDRANT_HEADERS, timeout=10)
        r.raise_for_status()
        info = r.json()["result"]
        log.info(f"Collection '{COLLECTION}': {info['points_count']:,} vectors, status={info['status']}")
    except Exception as e:
        log.error(f"Qdrant collection not available: {e}")
        sys.exit(1)

    # Load or bootstrap state
    if args.reset_state and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    state = load_state()
    if not state:
        state = init_state_from_qdrant()

    log.info(f"Known files: {len(state):,}")

    embedder = SentinelEmbedder()

    if args.once:
        run_scan(state, embedder)
        return

    # Continuous mode
    while not _shutdown.is_set():
        try:
            state = run_scan(state, embedder)
        except Exception as e:
            log.error(f"Scan cycle failed: {e}")

        # Sleep with shutdown check
        for _ in range(args.interval):
            if _shutdown.is_set():
                break
            time.sleep(1)

    log.info("Sentinel shut down cleanly.")


if __name__ == "__main__":
    main()
