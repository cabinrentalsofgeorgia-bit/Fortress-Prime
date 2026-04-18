"""
Fortress Prime — Cross-Division Drawing Ingestion
=====================================================
Indexes engineering drawings (DWG/DXF) into ChromaDB for vector search
accessible by ALL divisions:

    - Iron Mountain (Legal)    → Searches surveys, easements, plats
    - The Drawing Board (Eng)  → Searches all A/E drawings
    - Guardian Ops             → Property condition drawings
    - Rainmaker (Finance)      → Construction cost documentation
    - Sovereign                → Cross-division intelligence

This tool reads all DWG/DXF files from NAS, extracts structured content
via the shared Drawing Reader, and indexes the extracted text + metadata
into ChromaDB using the same nomic-embed-text model as the legal vault.

Usage:
    python tools/drawing_ingest.py                # Full ingest
    python tools/drawing_ingest.py --stats        # Show index stats
    python tools/drawing_ingest.py --legal        # Ingest with legal extraction only
    python tools/drawing_ingest.py --reindex      # Drop and rebuild

Requires: pip install ezdxf chromadb requests
"""

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

# Fortress path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.drawing_reader import (
    read_drawing,
    extract_for_vectordb,
    extract_for_legal,
    inventory_drawings,
)

# --- CONFIG ---
OLLAMA_EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768

# ChromaDB — use HTTP client (shared with Legal API)
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8002"))

# Collection name — same as Legal API's fortress_docs for unified search
# Also creates a dedicated engineering_drawings collection for division-specific queries
UNIFIED_COLLECTION = os.getenv("LEGAL_COLLECTION", "fortress_docs")
ENGINEERING_COLLECTION = "engineering_drawings"

# NAS roots to scan
NAS_ROOTS = [
    "/mnt/fortress_nas/Business_Prime/CROG",
    "/mnt/fortress_nas/Enterprise_War_Room",
]

# Log
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs/drawing_ingest"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("drawing_ingest")


# =============================================================================
# EMBEDDING
# =============================================================================

def get_embedding(text: str, retries: int = 2) -> Optional[List[float]]:
    """Generate 768-dim embedding via Ollama nomic-embed-text."""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                OLLAMA_EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text[:2000]},
                timeout=30,
            )
            if resp.status_code == 200:
                emb = resp.json().get("embedding", [])
                if emb and len(emb) == EMBED_DIM:
                    return emb
        except Exception as e:
            if attempt == retries:
                logger.error(f"Embedding failed: {e}")
                return None
            time.sleep(0.5)
    return None


# =============================================================================
# CHROMADB
# =============================================================================

def get_chroma_client():
    """Get HTTP ChromaDB client (shared with Legal API)."""
    import chromadb
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def get_or_create_collection(client, name: str):
    """Get or create a ChromaDB collection."""
    return client.get_or_create_collection(
        name=name,
        metadata={
            "description": f"Fortress Prime — {name}",
            "embed_model": EMBED_MODEL,
            "embed_dim": str(EMBED_DIM),
        },
    )


# =============================================================================
# INGESTION
# =============================================================================

def ingest_drawings(
    unified: bool = True,
    engineering: bool = True,
    reindex: bool = False,
    legal_only: bool = False,
) -> Dict[str, Any]:
    """
    Ingest all DWG/DXF files into ChromaDB collections.

    Args:
        unified: Index into the unified fortress_docs collection (for Legal/RAG)
        engineering: Index into the engineering_drawings collection
        reindex: Drop existing drawing entries and rebuild
        legal_only: Only extract legal-relevant content (surveys, plats, easements)

    Returns:
        Summary dict with counts.
    """
    t0 = time.time()

    logger.info("Starting drawing ingestion...")
    logger.info(f"Scanning NAS roots: {NAS_ROOTS}")

    # Discover all drawings
    inv = inventory_drawings(NAS_ROOTS)
    all_files = inv.get("files", [])
    logger.info(
        f"Found {len(all_files)} unique drawing files "
        f"({inv['dwg_count']} DWG, {inv['dxf_count']} DXF)"
    )

    if not all_files:
        return {"status": "no_files", "total_files": 0}

    # Connect to ChromaDB
    try:
        client = get_chroma_client()
        collections = {}

        if unified:
            if reindex:
                # Don't drop the entire unified collection — just delete drawing entries
                col = get_or_create_collection(client, UNIFIED_COLLECTION)
                try:
                    col.delete(where={"source": "engineering_drawing"})
                    logger.info(f"Cleared engineering drawings from {UNIFIED_COLLECTION}")
                except Exception:
                    pass  # Collection may be empty
            collections["unified"] = get_or_create_collection(client, UNIFIED_COLLECTION)

        if engineering:
            if reindex:
                try:
                    client.delete_collection(ENGINEERING_COLLECTION)
                    logger.info(f"Dropped {ENGINEERING_COLLECTION} for reindex")
                except Exception:
                    pass
            collections["engineering"] = get_or_create_collection(
                client, ENGINEERING_COLLECTION
            )

    except Exception as e:
        logger.error(f"ChromaDB connection failed: {e}")
        return {"status": "error", "error": str(e)}

    # Process each file
    total_chunks = 0
    indexed_files = 0
    failed_files = 0
    skipped_files = 0

    for i, finfo in enumerate(all_files):
        filepath = finfo["filepath"]
        filename = finfo["filename"]
        ext = finfo["extension"]

        print(
            f"  [{i+1}/{len(all_files)}] {filename[:55]}...",
            end=" ",
            flush=True,
        )

        # Only process DXF files directly (DWG are handled through companions)
        if ext == ".dwg":
            # read_drawing handles DWG → companion DXF fallback
            pass

        try:
            chunks = extract_for_vectordb(filepath)
        except Exception as e:
            logger.warning(f"Extraction failed for {filename}: {e}")
            print(f"(error)")
            failed_files += 1
            continue

        if not chunks:
            print("(no content)")
            skipped_files += 1
            continue

        # Embed and index each chunk
        file_indexed = 0
        for chunk in chunks:
            embedding = get_embedding(chunk["text"])
            if not embedding:
                continue

            # Add to each target collection
            for col_name, col in collections.items():
                chunk_id = f"{col_name}_{chunk['id']}"

                # Check if already exists
                try:
                    existing = col.get(ids=[chunk_id])
                    if existing and existing["ids"]:
                        continue
                except Exception:
                    pass

                try:
                    col.add(
                        ids=[chunk_id],
                        embeddings=[embedding],
                        documents=[chunk["text"]],
                        metadatas=[chunk["metadata"]],
                    )
                    file_indexed += 1
                except Exception as e:
                    logger.warning(f"Index failed for {chunk_id}: {e}")

        total_chunks += file_indexed
        indexed_files += 1
        print(f"({file_indexed} chunks)")

        # Periodic checkpoint log
        if (i + 1) % 10 == 0:
            logger.info(
                f"Progress: {i+1}/{len(all_files)} files, "
                f"{total_chunks} chunks indexed"
            )

    elapsed = time.time() - t0

    result = {
        "status": "complete",
        "total_files_scanned": len(all_files),
        "indexed_files": indexed_files,
        "failed_files": failed_files,
        "skipped_files": skipped_files,
        "total_chunks": total_chunks,
        "elapsed_seconds": round(elapsed, 1),
        "collections": list(collections.keys()),
        "timestamp": datetime.now().isoformat(),
    }

    # Log the run
    _log_ingest(result)

    return result


def show_stats():
    """Show drawing index statistics."""
    try:
        client = get_chroma_client()
    except Exception as e:
        print(f"  ChromaDB unavailable: {e}")
        return

    print("\n" + "=" * 70)
    print("  DRAWING INDEX — CHROMADB STATISTICS")
    print("=" * 70)

    for col_name in [UNIFIED_COLLECTION, ENGINEERING_COLLECTION]:
        try:
            col = client.get_collection(col_name)
            count = col.count()
            print(f"\n  Collection: {col_name}")
            print(f"  Total documents: {count:,}")

            # Sample to get category distribution
            sample = col.peek(limit=100)
            categories = {}
            sources = {}
            if sample.get("metadatas"):
                for meta in sample["metadatas"]:
                    if meta:
                        cat = meta.get("category", "unknown")
                        categories[cat] = categories.get(cat, 0) + 1
                        src = meta.get("source", "unknown")
                        sources[src] = sources.get(src, 0) + 1

            if categories:
                print(f"  Category distribution (sample):")
                for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
                    print(f"    {cat:<30} {cnt}")

        except Exception as e:
            print(f"\n  Collection '{col_name}': not found or empty ({e})")

    # NAS inventory
    inv = inventory_drawings(NAS_ROOTS)
    print(f"\n  NAS Drawing Inventory:")
    print(f"    Total files:  {inv['total_files']:,}")
    print(f"    DWG files:    {inv['dwg_count']:,}")
    print(f"    DXF files:    {inv['dxf_count']:,}")
    print(f"    Total size:   {inv['total_size_bytes']/1e6:.1f} MB")

    print(f"\n{'='*70}\n")


def _log_ingest(result: Dict):
    """Persist ingestion log."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(
            LOG_DIR, f"ingest_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        with open(log_file, "w") as f:
            json.dump(result, f, indent=2)
        logger.info(f"Log written: {log_file}")
    except Exception:
        pass


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Cross-Division Drawing Ingestion"
    )
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument(
        "--legal", action="store_true",
        help="Index only into unified collection (for Legal division)"
    )
    parser.add_argument(
        "--reindex", action="store_true",
        help="Drop existing drawing entries and rebuild"
    )
    parser.add_argument(
        "--engineering-only", action="store_true",
        help="Index only into engineering_drawings collection"
    )

    args = parser.parse_args()

    print("\n  FORTRESS PRIME — CROSS-DIVISION DRAWING INGESTION")
    print(f"  ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"  Embed Model: {EMBED_MODEL}")
    print(f"  NAS Roots: {', '.join(NAS_ROOTS)}")

    if args.stats:
        show_stats()
        return

    result = ingest_drawings(
        unified=not args.engineering_only,
        engineering=not args.legal,
        reindex=args.reindex,
        legal_only=args.legal,
    )

    print(f"\n  {'='*60}")
    print(f"  INGESTION COMPLETE")
    print(f"  {'='*60}")
    print(f"  Files indexed:   {result.get('indexed_files', 0):,}")
    print(f"  Failed files:    {result.get('failed_files', 0):,}")
    print(f"  Total chunks:    {result.get('total_chunks', 0):,}")
    print(f"  Elapsed:         {result.get('elapsed_seconds', 0):.1f}s")
    print(f"  Collections:     {', '.join(result.get('collections', []))}")
    print(f"  {'='*60}\n")


if __name__ == "__main__":
    main()
