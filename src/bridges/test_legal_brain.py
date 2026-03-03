"""
DIVISION 1: LEGAL CORTEX PROBE
================================
Tests connectivity to the ChromaDB vector database and validates
that the OCR'd legal documents are retrievable.

Usage:
    python3 src/bridges/test_legal_brain.py

Module: CF-03 Iron Mountain — Division 1 Legal
"""

import chromadb
import os
import sys
import time

# --- CONFIGURATION ---
CHROMA_HOST = "localhost"
CHROMA_PORT = 8002
CHROMA_PATH = "/mnt/ai_fast/chroma_db"


def probe_mind():
    # Disk check first
    print(f"  Database path: {CHROMA_PATH}")
    if os.path.exists(CHROMA_PATH):
        total_size = 0
        file_count = 0
        for dirpath, _, filenames in os.walk(CHROMA_PATH):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_size += os.path.getsize(fp)
                except OSError:
                    pass
                file_count += 1
        print(f"  On disk: {total_size / (1024**3):.2f} GB across {file_count} files")
    else:
        print(f"  WARNING: Path not found on disk")

    print()

    # Connect via HTTP (server is running on port 8002 per crontab)
    print(f"  Connecting to ChromaDB server at {CHROMA_HOST}:{CHROMA_PORT}...")
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        hb = client.heartbeat()
        print(f"  Server heartbeat: OK (ns={hb})")
    except Exception as e:
        print(f"  HTTP connection failed: {e}")
        print(f"  Trying direct persistence fallback...")
        try:
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            print(f"  Connected via direct persistence")
        except Exception as e2:
            print(f"  FATAL: Cannot connect to ChromaDB: {e2}")
            return

    print()

    # List collections
    print("  Enumerating collections...")
    try:
        collections = client.list_collections()
    except Exception as e:
        print(f"  Failed to list collections: {e}")
        return

    print(f"  Found {len(collections)} collections")
    print()

    total_docs = 0

    for col_name in collections:
        # In chromadb 1.4.x, list_collections returns collection names (strings)
        # We need to get the actual collection object
        try:
            if isinstance(col_name, str):
                col = client.get_collection(col_name)
                name = col_name
            else:
                col = col_name
                name = col.name
        except Exception as e:
            print(f"    [{col_name}]: Failed to open — {e}")
            continue

        try:
            count = col.count()
        except Exception as e:
            print(f"    [{name}]: Failed to count — {e}")
            continue

        total_docs += count
        print(f"    [{name}]: {count:,} documents")

        # Peek at metadata structure
        try:
            peek = col.peek(limit=1)
            if peek and peek.get("metadatas") and peek["metadatas"]:
                meta = peek["metadatas"][0]
                if meta:
                    print(f"      Metadata keys: {list(meta.keys())}")
                    # Show a sample metadata value
                    for k, v in meta.items():
                        val_str = str(v)[:80]
                        print(f"        {k}: {val_str}")
            if peek and peek.get("ids") and peek["ids"]:
                print(f"      Sample ID: {peek['ids'][0][:80]}")
        except Exception as e:
            print(f"      Peek failed: {e}")

        # Test queries
        if count > 0:
            queries = ["easement agreement", "property deed", "lease contract"]
            for q in queries:
                try:
                    start = time.time()
                    results = col.query(
                        query_texts=[q],
                        n_results=3,
                    )
                    ms = (time.time() - start) * 1000
                    print(f"      Query '{q}': {ms:.1f}ms, {len(results['documents'][0])} results")
                    if results["documents"] and results["documents"][0]:
                        doc = results["documents"][0][0]
                        preview = doc[:200].replace("\n", " ").strip()
                        print(f"        -> {preview}")
                    if results.get("distances") and results["distances"][0]:
                        print(f"        -> Distance: {results['distances'][0][0]:.4f}")
                    break  # One successful query per collection is enough
                except Exception as e:
                    print(f"      Query '{q}' failed: {e}")

        print()

    # Summary
    print("=" * 50)
    print(f"  TOTAL VECTORS: {total_docs:,}")

    if total_docs > 0:
        print("  STATUS: CORTEX IS ALIVE")
        print("  The Librarian is ready for the search interface.")
    elif len(collections) > 0:
        print("  STATUS: SHELVES EXIST BUT EMPTY")
        print("  Collections found but no documents. Re-indexing needed.")
    else:
        print("  STATUS: NO COLLECTIONS")
        print("  ChromaDB is running but has no data. Full indexing needed.")
    print("=" * 50)


if __name__ == "__main__":
    print("=" * 60)
    print("  DIVISION 1: LEGAL CORTEX PROBE")
    print("=" * 60)
    print()
    probe_mind()
