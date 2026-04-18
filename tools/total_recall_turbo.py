#!/usr/bin/env python3
"""
OPERATION TOTAL RECALL — TURBO MODE
====================================
Parallel document ingestion across all 4 DGX Spark GPU nodes.
Fans out embedding work to 4x nomic-embed-text instances simultaneously.

Architecture:
  - 4 embedding workers (one per GPU node)
  - 8 file-reader threads feeding a shared queue
  - Batch upserts to Qdrant (100 vectors per batch)
  - Resume support: skips already-ingested files

Usage:
  python tools/total_recall_turbo.py --resume    # Continue where we left off
  python tools/total_recall_turbo.py             # Full re-ingest
"""

import os
import sys
import time
import hashlib
import argparse
import logging
import queue
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get_ollama_endpoints

# ─── Configuration ─────────────────────────────────────────────────

EMBED_NODES = get_ollama_endpoints()
EMBED_MODEL = "nomic-embed-text"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
COLLECTION = "fortress_knowledge"

# Worker config
EMBED_WORKERS = len(EMBED_NODES)  # 4 — one per GPU
FILE_READERS = 8                  # parallel file readers
QDRANT_BATCH = 100                # vectors per upsert
QUEUE_MAX = 500                   # max chunks in flight

# Directories
NAS_DIRS = [
    "/mnt/fortress_nas/Business_Prime",
    "/mnt/fortress_nas/Corporate_Legal",
    "/mnt/fortress_nas/Financial_Ledger",
    "/mnt/fortress_nas/Real_Estate_Assets",
    "/mnt/fortress_nas/Enterprise_War_Room",
    "/mnt/fortress_nas/Communications",
    "/mnt/fortress_nas/sectors",
]
PROJECT_DIR = "/home/admin/Fortress-Prime"

EXTENSIONS = {
    ".pdf", ".txt", ".md", ".csv", ".html", ".eml",
    ".py", ".sh", ".sql", ".yaml", ".yml", ".json", ".doc",
}
SKIP_DIRS = {
    "__pycache__", ".git", ".cursor", "node_modules", "venv",
    ".venv", "#recycle", "@eaDir", "chroma_db", "nim_cache",
    "models", "titan_engine", "raw_images",
}
SKIP_FILES = {".env", "credentials", ".key", ".pem", ".p12"}

MAX_CHARS = 2000       # chars per chunk (~500 tokens)
OVERLAP_CHARS = 400    # overlap
MAX_FILE_SIZE = 50_000_000

# ─── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("turbo")


# ─── Text Extraction ──────────────────────────────────────────────

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


# ─── File Crawler ─────────────────────────────────────────────────

def crawl_all(directories: list[str]) -> list[str]:
    files = []
    for root_dir in directories:
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
                    sz = os.path.getsize(fpath)
                    if sz < 50 or sz > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(fpath)
    return files


# ─── Already-ingested tracker ─────────────────────────────────────

def get_ingested_files() -> set:
    """Scroll through Qdrant to get all unique source_file values."""
    files = set()
    try:
        offset = None
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
                if sf:
                    files.add(sf)

            offset = result.get("next_page_offset")
            if offset is None:
                break
    except Exception as e:
        log.warning(f"Failed to fetch ingested files: {e}")
    return files


# ─── Parallel Embedding Engine ────────────────────────────────────

class TurboEmbedder:
    """Distributes embedding work round-robin across 4 GPU nodes."""

    def __init__(self):
        self._node_idx = 0
        self._lock = threading.Lock()
        self.stats = {
            "embedded": 0,
            "stored": 0,
            "errors": 0,
            "files_done": 0,
            "files_skipped": 0,
        }
        self._stats_lock = threading.Lock()

    def _next_node(self) -> str:
        with self._lock:
            url = EMBED_NODES[self._node_idx]
            self._node_idx = (self._node_idx + 1) % len(EMBED_NODES)
            return url

    def embed_one(self, text: str) -> list:
        """Embed a single text, round-robin across nodes."""
        node = self._next_node()
        resp = requests.post(
            f"{node}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])

    def process_file(self, fpath: str) -> int:
        """Extract, chunk, embed, and store a single file."""
        try:
            text = extract_file(fpath)
            if not text or len(text.strip()) < 50:
                with self._stats_lock:
                    self.stats["files_skipped"] += 1
                return 0

            chunks = chunk_text(text, fpath)
            if not chunks:
                with self._stats_lock:
                    self.stats["files_skipped"] += 1
                return 0

            # Embed all chunks (distributed across nodes)
            points = []
            for chunk in chunks:
                try:
                    embedding = self.embed_one(chunk["text"])
                    if not embedding:
                        continue

                    point_id = int(hashlib.md5(
                        f"{chunk['source']}:{chunk['char_offset']}".encode()
                    ).hexdigest()[:16], 16)

                    points.append({
                        "id": point_id,
                        "vector": embedding,
                        "payload": {
                            "text": chunk["text"][:2000],
                            "source_file": chunk["source"],
                            "chunk_num": chunk["chunk_num"],
                            "char_offset": chunk["char_offset"],
                            "file_type": Path(chunk["source"]).suffix.lower(),
                            "directory": str(Path(chunk["source"]).parent),
                            "file_name": Path(chunk["source"]).name,
                        }
                    })

                    with self._stats_lock:
                        self.stats["embedded"] += 1

                except Exception as e:
                    with self._stats_lock:
                        self.stats["errors"] += 1

            # Batch upsert to Qdrant
            stored = 0
            for i in range(0, len(points), QDRANT_BATCH):
                batch = points[i:i + QDRANT_BATCH]
                try:
                    resp = requests.put(
                        f"{QDRANT_URL}/collections/{COLLECTION}/points",
                        json={"points": batch},
                        headers=QDRANT_HEADERS,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    stored += len(batch)
                except Exception as e:
                    log.warning(f"Qdrant upsert failed: {e}")
                    with self._stats_lock:
                        self.stats["errors"] += 1

            with self._stats_lock:
                self.stats["stored"] += stored
                self.stats["files_done"] += 1

            return stored

        except Exception as e:
            with self._stats_lock:
                self.stats["errors"] += 1
            return 0


# ─── Main Pipeline ────────────────────────────────────────────────

def run_turbo(directories: list[str], resume: bool = False):
    log.info("=" * 60)
    log.info("OPERATION TOTAL RECALL — TURBO MODE")
    log.info(f"  GPU Nodes: {len(EMBED_NODES)}")
    log.info(f"  Workers: {FILE_READERS} file readers")
    log.info("=" * 60)

    # Crawl
    log.info("\nCrawling directories...")
    all_files = crawl_all(directories)
    log.info(f"Total files found: {len(all_files):,}")

    # Type breakdown
    by_ext = {}
    for f in all_files:
        ext = Path(f).suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
    for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
        log.info(f"  {ext}: {count:,}")

    # Resume filter
    if resume:
        log.info("\nChecking already-ingested files...")
        already = get_ingested_files()
        before = len(all_files)
        all_files = [f for f in all_files if f not in already]
        log.info(f"  Already done: {before - len(all_files):,}")
        log.info(f"  Remaining: {len(all_files):,}")

    if not all_files:
        log.info("Nothing to ingest!")
        return

    # Run parallel
    engine = TurboEmbedder()
    total = len(all_files)
    start = time.time()

    log.info(f"\nLaunching {FILE_READERS} parallel workers across {len(EMBED_NODES)} GPU nodes...")

    with ThreadPoolExecutor(max_workers=FILE_READERS) as pool:
        futures = {pool.submit(engine.process_file, f): f for f in all_files}

        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            try:
                future.result()
            except Exception as e:
                log.warning(f"File failed: {e}")

            if done_count % 200 == 0 or done_count == total:
                elapsed = time.time() - start
                rate = engine.stats["files_done"] / elapsed if elapsed > 0 else 0
                remaining = total - done_count
                eta = remaining / rate / 60 if rate > 0 else 0
                log.info(
                    f"[{done_count:,}/{total:,}] "
                    f"files={engine.stats['files_done']:,} "
                    f"vectors={engine.stats['stored']:,} "
                    f"errors={engine.stats['errors']} "
                    f"rate={rate:.1f}/s "
                    f"ETA={eta:.0f}min"
                )

    elapsed = time.time() - start

    # Final report
    log.info("\n" + "=" * 60)
    log.info("OPERATION TOTAL RECALL — TURBO COMPLETE")
    log.info("=" * 60)
    log.info(f"  Files processed: {engine.stats['files_done']:,}")
    log.info(f"  Files skipped:   {engine.stats['files_skipped']:,}")
    log.info(f"  Errors:          {engine.stats['errors']}")
    log.info(f"  Vectors stored:  {engine.stats['stored']:,}")
    log.info(f"  Time:            {elapsed/60:.1f} minutes")
    log.info(f"  Rate:            {engine.stats['files_done']/elapsed:.1f} files/sec")
    log.info(f"  Throughput:      {engine.stats['stored']/elapsed:.0f} vectors/sec")

    # Collection status
    resp = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", headers=QDRANT_HEADERS)
    info = resp.json()["result"]
    log.info(f"\n  Collection: {COLLECTION}")
    log.info(f"  Total vectors: {info['points_count']:,}")
    log.info(f"  Status: {info['status']}")


def main():
    parser = argparse.ArgumentParser(description="Total Recall TURBO — 4-GPU parallel ingestion")
    parser.add_argument("--resume", action="store_true", help="Skip already-ingested files")
    parser.add_argument("--project-only", action="store_true")
    parser.add_argument("--nas-only", action="store_true")
    parser.add_argument("--dir", type=str)
    args = parser.parse_args()

    if args.dir:
        dirs = [args.dir]
    elif args.project_only:
        dirs = [PROJECT_DIR]
    elif args.nas_only:
        dirs = NAS_DIRS
    else:
        dirs = NAS_DIRS + [PROJECT_DIR]

    run_turbo(dirs, resume=args.resume)


if __name__ == "__main__":
    main()
