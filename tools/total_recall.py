#!/usr/bin/env python3
"""
OPERATION TOTAL RECALL — Fortress Knowledge Ingestion Pipeline
==============================================================
Ingests documents from the NAS and project directory into Qdrant
(fortress_knowledge collection), giving AI models semantic search
over every PDF, text file, code file, and document in the Fortress.

Architecture:
  1. CRAWL  — Walk target directories, filter by extension
  2. EXTRACT — Pull text from PDFs (pypdf), plain text, code files
  3. CHUNK  — Split into ~500-token overlapping chunks
  4. EMBED  — Generate vectors via nomic-embed-text (Ollama)
  5. STORE  — Upsert into Qdrant fortress_knowledge collection

Usage:
  python tools/total_recall.py                    # Full ingest (NAS + project)
  python tools/total_recall.py --project-only     # Just project files
  python tools/total_recall.py --nas-only         # Just NAS files
  python tools/total_recall.py --dir /path/to/dir # Custom directory
  python tools/total_recall.py --dry-run          # Count files, don't ingest
  python tools/total_recall.py --resume           # Skip files already ingested

Constitution Reference:
  - Article I: Data Sovereignty — all processing is local (Ollama + Qdrant)
  - Article II: Config-driven — endpoints from config.py
"""

import os
import sys
import time
import json
import hashlib
import argparse
import logging
from pathlib import Path
from typing import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ─── Configuration ─────────────────────────────────────────────────

OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
COLLECTION = "fortress_knowledge"

# Directories to ingest
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

# File types to ingest
EXTENSIONS = {
    # Documents
    ".pdf", ".txt", ".md", ".csv", ".html", ".eml",
    # Code
    ".py", ".sh", ".sql", ".yaml", ".yml", ".json",
    # Office (text extraction only)
    ".doc",
}

# Skip patterns
SKIP_DIRS = {
    "__pycache__", ".git", ".cursor", "node_modules", "venv",
    ".venv", "#recycle", "@eaDir", "chroma_db", "nim_cache",
    "models", "titan_engine", "raw_images",
}
SKIP_FILES = {".env", "credentials", ".key", ".pem", ".p12"}

# Chunking
CHUNK_SIZE = 500       # tokens (approximate via chars / 4)
CHUNK_OVERLAP = 100    # token overlap
MAX_CHARS = CHUNK_SIZE * 4
OVERLAP_CHARS = CHUNK_OVERLAP * 4

# Batching
EMBED_BATCH_SIZE = 32  # Vectors per Qdrant upsert batch
MAX_FILE_SIZE = 50_000_000  # 50MB max per file

# ─── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("total_recall")


# ─── Text Extraction ──────────────────────────────────────────────

def extract_pdf(path: str) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        log.warning(f"PDF extraction failed for {path}: {e}")
        return ""


def extract_text(path: str) -> str:
    """Extract text from a plain text file."""
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except Exception as e:
        log.warning(f"Text extraction failed for {path}: {e}")
        return ""


def extract_file(path: str) -> str:
    """Route to the correct extractor based on extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    else:
        return extract_text(path)


# ─── Chunking ─────────────────────────────────────────────────────

def chunk_text(text: str, source: str) -> Generator[dict, None, None]:
    """Split text into overlapping chunks with metadata."""
    if not text or len(text.strip()) < 50:
        return

    # Clean up
    text = text.replace("\x00", "").strip()

    idx = 0
    chunk_num = 0
    while idx < len(text):
        end = idx + MAX_CHARS
        chunk = text[idx:end]

        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break
            last_para = chunk.rfind("\n\n")
            if last_para > MAX_CHARS // 2:
                chunk = chunk[:last_para]
                end = idx + last_para
            else:
                # Look for sentence break
                last_period = chunk.rfind(". ")
                if last_period > MAX_CHARS // 2:
                    chunk = chunk[:last_period + 1]
                    end = idx + last_period + 1

        chunk = chunk.strip()
        if len(chunk) > 50:
            chunk_num += 1
            yield {
                "text": chunk,
                "source": source,
                "chunk_num": chunk_num,
                "char_offset": idx,
            }

        # Advance with overlap
        idx = end - OVERLAP_CHARS if end < len(text) else len(text)


# ─── Embedding ────────────────────────────────────────────────────

def embed_text(text: str) -> list:
    """Generate embedding via Ollama nomic-embed-text."""
    resp = requests.post(OLLAMA_EMBED_URL, json={
        "model": EMBED_MODEL,
        "prompt": text[:8000],  # Limit input to avoid OOM
    }, timeout=30)
    resp.raise_for_status()
    return resp.json().get("embedding", [])


def embed_batch(chunks: list[dict]) -> list[dict]:
    """Embed a batch of chunks. Returns chunks with embeddings added."""
    results = []
    for chunk in chunks:
        try:
            embedding = embed_text(chunk["text"])
            if embedding:
                chunk["embedding"] = embedding
                results.append(chunk)
        except Exception as e:
            log.warning(f"Embedding failed for chunk from {chunk['source']}: {e}")
    return results


# ─── Qdrant Storage ──────────────────────────────────────────────

def upsert_batch(chunks: list[dict]) -> int:
    """Upsert a batch of embedded chunks into Qdrant."""
    points = []
    for chunk in chunks:
        if "embedding" not in chunk:
            continue

        # Generate deterministic ID from source + offset
        point_id = hashlib.md5(
            f"{chunk['source']}:{chunk['char_offset']}".encode()
        ).hexdigest()
        # Qdrant needs UUID or unsigned int — use first 16 hex chars as int
        numeric_id = int(point_id[:16], 16)

        points.append({
            "id": numeric_id,
            "vector": chunk["embedding"],
            "payload": {
                "text": chunk["text"][:2000],  # Store preview
                "source_file": chunk["source"],
                "chunk_num": chunk["chunk_num"],
                "char_offset": chunk["char_offset"],
                "file_type": Path(chunk["source"]).suffix.lower(),
                "directory": str(Path(chunk["source"]).parent),
                "file_name": Path(chunk["source"]).name,
            }
        })

    if not points:
        return 0

    resp = requests.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={"points": points},
        headers=QDRANT_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return len(points)


def get_ingested_files() -> set:
    """Get set of already-ingested source files from Qdrant."""
    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
            json={
                "limit": 100,
                "with_payload": {"include": ["source_file"]},
                "with_vector": False,
            },
            headers=QDRANT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        points = resp.json().get("result", {}).get("points", [])
        files = set()
        for p in points:
            sf = p.get("payload", {}).get("source_file", "")
            if sf:
                files.add(sf)

        # Scroll to get all unique files
        offset = resp.json().get("result", {}).get("next_page_offset")
        while offset:
            resp = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                json={
                    "offset": offset,
                    "limit": 100,
                    "with_payload": {"include": ["source_file"]},
                    "with_vector": False,
                },
                headers=QDRANT_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            for p in result.get("points", []):
                sf = p.get("payload", {}).get("source_file", "")
                if sf:
                    files.add(sf)
            offset = result.get("next_page_offset")

        return files
    except Exception:
        return set()


# ─── File Crawler ─────────────────────────────────────────────────

def crawl_directory(root: str) -> Generator[str, None, None]:
    """Walk a directory tree and yield ingestible file paths."""
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            # Skip hidden and excluded files
            if fname.startswith("."):
                continue
            if any(skip in fname.lower() for skip in SKIP_FILES):
                continue

            fpath = os.path.join(dirpath, fname)
            ext = Path(fpath).suffix.lower()

            if ext not in EXTENSIONS:
                continue

            # Skip huge files
            try:
                if os.path.getsize(fpath) > MAX_FILE_SIZE:
                    continue
                if os.path.getsize(fpath) < 50:
                    continue
            except OSError:
                continue

            yield fpath


# ─── Main Pipeline ────────────────────────────────────────────────

def ingest_file(fpath: str, stats: dict) -> int:
    """Ingest a single file: extract -> chunk -> embed -> store."""
    try:
        text = extract_file(fpath)
        if not text or len(text.strip()) < 50:
            stats["skipped"] += 1
            return 0

        chunks = list(chunk_text(text, fpath))
        if not chunks:
            stats["skipped"] += 1
            return 0

        # Embed and store in batches
        total_stored = 0
        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i:i + EMBED_BATCH_SIZE]
            embedded = embed_batch(batch)
            if embedded:
                stored = upsert_batch(embedded)
                total_stored += stored

        stats["files_done"] += 1
        stats["chunks_total"] += total_stored
        return total_stored

    except Exception as e:
        log.error(f"Failed to ingest {fpath}: {e}")
        stats["errors"] += 1
        return 0


def run_pipeline(
    directories: list[str],
    dry_run: bool = False,
    resume: bool = False,
):
    """Main ingestion pipeline."""
    log.info("=" * 60)
    log.info("OPERATION TOTAL RECALL — Document Ingestion")
    log.info("=" * 60)

    # Collect all files
    all_files = []
    for d in directories:
        if not os.path.exists(d):
            log.warning(f"Directory not found: {d}")
            continue
        files = list(crawl_directory(d))
        log.info(f"  {d}: {len(files)} files")
        all_files.extend(files)

    log.info(f"\nTotal files to process: {len(all_files)}")

    # File type breakdown
    by_ext = {}
    for f in all_files:
        ext = Path(f).suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
    for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
        log.info(f"  {ext}: {count}")

    if dry_run:
        log.info("\n[DRY RUN] No files will be ingested.")
        return

    # Resume: skip already-ingested files
    if resume:
        already = get_ingested_files()
        before = len(all_files)
        all_files = [f for f in all_files if f not in already]
        log.info(f"\n[RESUME] Skipping {before - len(all_files)} already-ingested files")
        log.info(f"  Remaining: {len(all_files)} files")

    if not all_files:
        log.info("Nothing to ingest!")
        return

    # Process files
    stats = {"files_done": 0, "chunks_total": 0, "errors": 0, "skipped": 0}
    start_time = time.time()
    total = len(all_files)

    for i, fpath in enumerate(all_files):
        stored = ingest_file(fpath, stats)

        # Progress reporting every 50 files
        if (i + 1) % 50 == 0 or i == total - 1:
            elapsed = time.time() - start_time
            rate = stats["files_done"] / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            log.info(
                f"[{i+1}/{total}] files={stats['files_done']} "
                f"chunks={stats['chunks_total']} errors={stats['errors']} "
                f"rate={rate:.1f}/s ETA={eta/60:.1f}min"
            )

    elapsed = time.time() - start_time

    # Final report
    log.info("\n" + "=" * 60)
    log.info("OPERATION TOTAL RECALL — COMPLETE")
    log.info("=" * 60)
    log.info(f"  Files processed: {stats['files_done']}")
    log.info(f"  Files skipped:   {stats['skipped']}")
    log.info(f"  Errors:          {stats['errors']}")
    log.info(f"  Chunks stored:   {stats['chunks_total']}")
    log.info(f"  Time:            {elapsed/60:.1f} minutes")
    log.info(f"  Rate:            {stats['files_done']/elapsed:.1f} files/sec")

    # Verify collection
    resp = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", headers=QDRANT_HEADERS)
    info = resp.json()["result"]
    log.info(f"\n  Collection: {COLLECTION}")
    log.info(f"  Total vectors: {info['points_count']:,}")
    log.info(f"  Status: {info['status']}")


# ─── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Operation Total Recall — NAS Document Ingestion")
    parser.add_argument("--project-only", action="store_true", help="Ingest only project files")
    parser.add_argument("--nas-only", action="store_true", help="Ingest only NAS files")
    parser.add_argument("--dir", type=str, help="Ingest a specific directory")
    parser.add_argument("--dry-run", action="store_true", help="Count files without ingesting")
    parser.add_argument("--resume", action="store_true", help="Skip already-ingested files")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build directory list
    if args.dir:
        directories = [args.dir]
    elif args.project_only:
        directories = [PROJECT_DIR]
    elif args.nas_only:
        directories = NAS_DIRS
    else:
        directories = NAS_DIRS + [PROJECT_DIR]

    run_pipeline(
        directories=directories,
        dry_run=args.dry_run,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
