#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — JORDI VISSER KNOWLEDGE INGESTION
═══════════════════════════════════════════════════════════════════════════════
Ingests Jordi Visser transcripts, PDFs, and commentary into Qdrant vector DB.

SOURCES:
    1. Downloaded transcripts (PDF/TXT/MD)
    2. YouTube transcripts (auto-generated or manual)
    3. Newsletter archives
    4. Podcast show notes

OUTPUT:
    - Qdrant collection: 'jordi_intel'
    - Embedding model: nomic-embed-text (768-dim)
    - Metadata: source_file, date, podcast_name, episode_num, timestamp, speaker

USAGE:
    # Ingest all files from default path
    python src/ingest_jordi_knowledge.py

    # Ingest specific directory
    python src/ingest_jordi_knowledge.py --source-path /path/to/transcripts

    # Re-ingest (drops and recreates collection)
    python src/ingest_jordi_knowledge.py --force-recreate

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import re
import json
import argparse
import hashlib
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

import requests
from pypdf import PdfReader
from tqdm import tqdm

# =============================================================================
# CONFIGURATION
# =============================================================================

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

COLLECTION_NAME = "jordi_intel"

EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

DEFAULT_SOURCE_PATH = "/mnt/fortress_nas/Intelligence/Jordi_Visser"

# Chunking parameters
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200  # overlap for context continuity


# =============================================================================
# EMBEDDING
# =============================================================================

def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding via local Ollama."""
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if emb and len(emb) == EMBED_DIM:
            return emb
    except Exception as e:
        print(f"  [ERROR] Embedding failed: {e}")
    return None


# =============================================================================
# QDRANT COLLECTION MANAGEMENT
# =============================================================================

def collection_exists(collection_name: str) -> bool:
    """Check if Qdrant collection exists."""
    try:
        resp = requests.get(
            f"{QDRANT_URL}/collections/{collection_name}",
            headers=QDRANT_HEADERS,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def create_collection(collection_name: str, force: bool = False):
    """Create Qdrant collection for Jordi knowledge."""
    if collection_exists(collection_name):
        if force:
            print(f"  [WARN] Deleting existing collection: {collection_name}")
            requests.delete(f"{QDRANT_URL}/collections/{collection_name}", headers=QDRANT_HEADERS)
        else:
            print(f"  [INFO] Collection '{collection_name}' already exists (use --force-recreate to drop)")
            return

    print(f"  [INFO] Creating collection: {collection_name}")

    payload = {
        "vectors": {
            "size": EMBED_DIM,
            "distance": "Cosine",
        },
        "optimizers_config": {
            "indexing_threshold": 10000,
        },
    }

    resp = requests.put(
        f"{QDRANT_URL}/collections/{collection_name}",
        headers=QDRANT_HEADERS,
        json=payload,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        print(f"  [SUCCESS] Collection created: {collection_name}")
    else:
        print(f"  [ERROR] Failed to create collection: {resp.text}")
        sys.exit(1)


# =============================================================================
# DOCUMENT PROCESSING
# =============================================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF."""
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        print(f"  [ERROR] Failed to read PDF {pdf_path}: {e}")
        return ""


def extract_text_from_file(file_path: str) -> str:
    """Extract text from various file formats."""
    ext = file_path.lower().split('.')[-1]

    if ext == 'pdf':
        return extract_text_from_pdf(file_path)
    elif ext in ('txt', 'md', 'markdown'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    else:
        print(f"  [WARN] Unsupported file type: {ext}")
        return ""


def extract_metadata_from_filename(filename: str) -> Dict[str, Any]:
    """
    Extract metadata from filename patterns.

    Expected patterns:
        - Blockworks_2024-12-15_Episode_342.pdf
        - Jordi_Visser_Interview_BTC_2024-01-20.txt
        - bankless_jordi_visser_2024_06_10.pdf
    """
    metadata = {
        "podcast_name": "unknown",
        "date": None,
        "episode_number": None,
        "speaker": "Jordi Visser",
    }

    # Extract date (YYYY-MM-DD or YYYY_MM_DD)
    date_match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', filename)
    if date_match:
        metadata["date"] = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

    # Extract podcast name (common patterns)
    lower = filename.lower()
    if 'blockworks' in lower:
        metadata["podcast_name"] = "Blockworks"
    elif 'bankless' in lower:
        metadata["podcast_name"] = "Bankless"
    elif 'unchained' in lower:
        metadata["podcast_name"] = "Unchained"
    elif 'interview' in lower:
        metadata["podcast_name"] = "Interview"

    # Extract episode number
    ep_match = re.search(r'episode[_\s]+(\d+)', filename, re.IGNORECASE)
    if ep_match:
        metadata["episode_number"] = int(ep_match.group(1))

    return metadata


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence boundary
        if end < len(text):
            last_period = chunk.rfind('.')
            last_newline = chunk.rfind('\n')
            break_point = max(last_period, last_newline)

            if break_point > chunk_size * 0.5:  # Only break if we're past halfway
                chunk = chunk[:break_point + 1]
                end = start + break_point + 1

        chunks.append(chunk.strip())
        start = end - overlap

    return chunks


# =============================================================================
# INGESTION PIPELINE
# =============================================================================

def ingest_document(
    file_path: str,
    collection_name: str,
) -> int:
    """
    Ingest a single document into Qdrant.

    Returns:
        Number of chunks successfully ingested.
    """
    # Extract text
    text = extract_text_from_file(file_path)
    if not text or len(text) < 100:
        print(f"  [SKIP] Insufficient text in {os.path.basename(file_path)}")
        return 0

    # Extract metadata
    filename = os.path.basename(file_path)
    metadata = extract_metadata_from_filename(filename)
    metadata["source_file"] = file_path
    metadata["file_name"] = filename

    # Chunk text
    chunks = chunk_text(text)

    # Ingest chunks
    points = []
    for i, chunk in enumerate(chunks):
        # Generate embedding
        embedding = embed_text(chunk)
        if not embedding:
            continue

        # Generate unique ID (UUID from hash of source + chunk index)
        hash_hex = hashlib.sha256(f"{file_path}_{i}".encode()).hexdigest()[:32]
        doc_id = str(uuid.UUID(hash_hex))

        # Build point
        point = {
            "id": doc_id,
            "vector": embedding,
            "payload": {
                "text": chunk,
                "source_file": file_path,
                "file_name": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "podcast_name": metadata.get("podcast_name", "unknown"),
                "date": metadata.get("date"),
                "episode_number": metadata.get("episode_number"),
                "speaker": metadata.get("speaker", "Jordi Visser"),
                "ingested_at": datetime.now().isoformat(),
            }
        }

        points.append(point)

    # Batch upload to Qdrant (batch size: 100)
    batch_size = 100
    uploaded = 0

    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        try:
            resp = requests.put(
                f"{QDRANT_URL}/collections/{collection_name}/points",
                headers=QDRANT_HEADERS,
                json={"points": batch},
                timeout=60,
            )
            if resp.status_code in (200, 201):
                uploaded += len(batch)
            else:
                print(f"  [ERROR] Batch upload failed: {resp.text}")
        except Exception as e:
            print(f"  [ERROR] Upload exception: {e}")

    return uploaded


def ingest_directory(
    source_path: str,
    collection_name: str,
) -> Dict[str, Any]:
    """
    Ingest all documents from a directory.

    Returns:
        Statistics dict with files processed, chunks uploaded, etc.
    """
    if not os.path.exists(source_path):
        print(f"  [ERROR] Source path not found: {source_path}")
        return {"error": "path_not_found"}

    # Find all supported files
    supported_exts = ('.pdf', '.txt', '.md', '.markdown')
    files = []
    for root, _, filenames in os.walk(source_path):
        for filename in filenames:
            if filename.lower().endswith(supported_exts):
                files.append(os.path.join(root, filename))

    if not files:
        print(f"  [WARN] No supported files found in {source_path}")
        return {"files_found": 0, "chunks_uploaded": 0}

    print(f"  [INFO] Found {len(files)} documents to ingest")

    # Ingest each file
    stats = {
        "files_found": len(files),
        "files_processed": 0,
        "chunks_uploaded": 0,
        "errors": 0,
    }

    for file_path in tqdm(files, desc="  Ingesting documents"):
        try:
            chunks = ingest_document(file_path, collection_name)
            if chunks > 0:
                stats["files_processed"] += 1
                stats["chunks_uploaded"] += chunks
            else:
                stats["errors"] += 1
        except Exception as e:
            print(f"\n  [ERROR] Failed to ingest {os.path.basename(file_path)}: {e}")
            stats["errors"] += 1

    return stats


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ingest Jordi Visser knowledge into Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source-path",
        default=DEFAULT_SOURCE_PATH,
        help=f"Path to Jordi transcripts directory (default: {DEFAULT_SOURCE_PATH})",
    )
    parser.add_argument(
        "--collection",
        default=COLLECTION_NAME,
        help=f"Qdrant collection name (default: {COLLECTION_NAME})",
    )
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Drop and recreate collection if it exists",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  FORTRESS PRIME — JORDI VISSER KNOWLEDGE INGESTION")
    print("=" * 70)
    print()

    # Check Qdrant connection
    try:
        resp = requests.get(f"{QDRANT_URL}/collections", headers=QDRANT_HEADERS, timeout=10)
        if resp.status_code != 200:
            print(f"  [ERROR] Qdrant not reachable at {QDRANT_URL}")
            sys.exit(1)
        print(f"  [OK] Qdrant online at {QDRANT_URL}")
    except Exception as e:
        print(f"  [ERROR] Cannot connect to Qdrant: {e}")
        sys.exit(1)

    # Check embedding service
    test_emb = embed_text("test")
    if not test_emb:
        print(f"  [ERROR] Embedding service not available at {EMBED_URL}")
        sys.exit(1)
    print(f"  [OK] Embedding service online ({EMBED_MODEL})")
    print()

    # Create/verify collection
    create_collection(args.collection, force=args.force_recreate)
    print()

    # Ingest documents
    print(f"  [INFO] Source path: {args.source_path}")
    stats = ingest_directory(args.source_path, args.collection)

    print()
    print("=" * 70)
    print("  INGESTION COMPLETE")
    print("=" * 70)
    print(f"  Files found:      {stats.get('files_found', 0)}")
    print(f"  Files processed:  {stats.get('files_processed', 0)}")
    print(f"  Chunks uploaded:  {stats.get('chunks_uploaded', 0)}")
    print(f"  Errors:           {stats.get('errors', 0)}")
    print()

    # Verify collection
    try:
        resp = requests.get(f"{QDRANT_URL}/collections/{args.collection}", headers=QDRANT_HEADERS, timeout=10)
        if resp.status_code == 200:
            info = resp.json().get("result", {})
            print(f"  Collection '{args.collection}' now contains:")
            print(f"    - {info.get('points_count', 0)} vectors")
            print(f"    - Status: {info.get('status', 'unknown')}")
    except Exception:
        pass

    print()
    print("  Next steps:")
    print("    1. Test search: python src/test_mcp_server.py search-jordi \"Bitcoin outlook\"")
    print("    2. Connect Cursor to MCP server")
    print("    3. Use @jordi in Cursor to query Jordi's knowledge")
    print()


if __name__ == "__main__":
    main()
