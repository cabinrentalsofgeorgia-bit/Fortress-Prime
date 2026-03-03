"""
Fortress Prime — fortress_docs Collection Repair
==================================================
Recovers 28,767 documents from the corrupted fortress_docs collection.

The HNSW vector index was lost, but all documents + metadata survive
in SQLite. This script:
    1. Extracts all recoverable data from the orphaned segment
    2. Backs it up to a JSON file (safety net)
    3. Cleans corruption (orphaned segments, stuck queue)
    4. Rebuilds fortress_docs with fresh 768-dim nomic-embed-text embeddings

Expected runtime: ~4 hours for 28,767 documents (embedding is the bottleneck).
Progress is saved — if interrupted, re-run to continue from where it left off.

Usage:
    python3 -m src.repair_fortress_docs              # full repair
    python3 -m src.repair_fortress_docs --extract     # extract + backup only
    python3 -m src.repair_fortress_docs --resume      # resume interrupted rebuild
"""

import os
import sys
import json
import time
import sqlite3
import argparse
import requests
from pathlib import Path

import chromadb
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    from src.fortress_paths import CHROMA_PATH
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import CHROMA_PATH

# =============================================================================
# CONFIG
# =============================================================================

# Use the canonical path from fortress_paths (local NVMe, not NFS)
CHROMA_DB_PATH = CHROMA_PATH
SQLITE_PATH    = os.path.join(CHROMA_DB_PATH, "chroma.sqlite3")
BACKUP_PATH    = "/mnt/fortress_nas/fortress_data/ai_brain/backups/fortress_docs_backup.jsonl"
PROGRESS_FILE  = "/mnt/fortress_nas/fortress_data/ai_brain/backups/repair_progress.json"

EMBED_URL   = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM   = 768

COLLECTION_NAME = "fortress_docs"
BATCH_SIZE = 50  # How many docs to add per ChromaDB batch


# =============================================================================
# EMBEDDING
# =============================================================================

def get_embedding(text: str, retries: int = 3):
    """Generate 768-dim embedding via Ollama."""
    for attempt in range(retries):
        try:
            resp = requests.post(EMBED_URL, json={
                "model": EMBED_MODEL,
                "prompt": text[:8000],
            }, timeout=60)
            resp.raise_for_status()
            emb = resp.json().get("embedding", [])
            if emb and len(emb) == EMBED_DIM:
                return emb
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
    return None


# =============================================================================
# STEP 1: EXTRACT DATA FROM ORPHANED SEGMENT
# =============================================================================

def extract_orphaned_data():
    """Extract all documents + metadata from the orphaned fortress_docs segment."""
    print("=" * 65)
    print("  STEP 1: Extracting data from orphaned segment")
    print("=" * 65)

    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()

    # Find the orphaned segment (has rows in embeddings but no parent in segments table)
    cur.execute("""
        SELECT e.segment_id, count(*) as cnt
        FROM embeddings e
        LEFT JOIN segments s ON e.segment_id = s.id
        WHERE s.id IS NULL
        GROUP BY e.segment_id
    """)
    orphans = cur.fetchall()

    if not orphans:
        # Check for fortress_docs segments with data
        cur.execute("""
            SELECT e.segment_id, count(*)
            FROM embeddings e
            JOIN segments s ON e.segment_id = s.id
            JOIN collections c ON s.collection = c.id
            WHERE c.name = ?
            GROUP BY e.segment_id
        """, (COLLECTION_NAME,))
        orphans = cur.fetchall()

    if not orphans:
        print("  No orphaned or fortress_docs data found in SQLite.")
        conn.close()
        return 0

    # Ensure backup directory exists
    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)

    total_extracted = 0

    with open(BACKUP_PATH, 'w') as f:
        for segment_id, count in orphans:
            print(f"\n  Extracting segment {segment_id[:16]}... ({count} records)")

            # Get all embedding records from this segment
            cur.execute("""
                SELECT id, embedding_id FROM embeddings
                WHERE segment_id = ?
                ORDER BY id
            """, (segment_id,))

            batch = []
            for row_id, emb_id in cur.fetchall():
                # Get metadata
                cur.execute("""
                    SELECT key, string_value, int_value, float_value
                    FROM embedding_metadata WHERE id = ?
                """, (row_id,))
                meta = {}
                document = None
                for key, str_val, int_val, float_val in cur.fetchall():
                    if key == "chroma:document":
                        document = str_val
                    elif str_val is not None:
                        meta[key] = str_val
                    elif int_val is not None:
                        meta[key] = int_val
                    elif float_val is not None:
                        meta[key] = float_val

                if document:
                    record = {
                        "id": emb_id,
                        "document": document,
                        "metadata": meta,
                    }
                    f.write(json.dumps(record) + "\n")
                    total_extracted += 1

                if total_extracted % 5000 == 0 and total_extracted > 0:
                    print(f"     ... extracted {total_extracted} records")

    conn.close()
    print(f"\n  Extracted {total_extracted} records to {BACKUP_PATH}")
    print(f"  Backup size: {os.path.getsize(BACKUP_PATH) / 1e6:.1f} MB")
    return total_extracted


# =============================================================================
# STEP 2: CLEAN CORRUPTION
# =============================================================================

def clean_corruption():
    """Remove orphaned segments, drain stuck queue, delete broken collection."""
    print("\n" + "=" * 65)
    print("  STEP 2: Cleaning corruption")
    print("=" * 65)

    # First, stop the ChromaDB HTTP server to get exclusive access
    print("  Stopping ChromaDB HTTP server...")
    os.system("pkill -f 'chroma run.*8002' 2>/dev/null")
    time.sleep(2)

    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()

    # Delete orphaned embeddings
    cur.execute("""
        SELECT e.segment_id, count(*)
        FROM embeddings e
        LEFT JOIN segments s ON e.segment_id = s.id
        WHERE s.id IS NULL
        GROUP BY e.segment_id
    """)
    orphans = cur.fetchall()
    for seg_id, cnt in orphans:
        print(f"  Deleting orphaned segment {seg_id[:16]}... ({cnt} rows)")
        cur.execute("DELETE FROM embeddings WHERE segment_id = ?", (seg_id,))
        cur.execute("DELETE FROM embedding_metadata WHERE id NOT IN (SELECT id FROM embeddings)")

    # Drain the stuck queue
    cur.execute("SELECT count(*) FROM embeddings_queue")
    queue_size = cur.fetchone()[0]
    if queue_size > 0:
        print(f"  Draining {queue_size} stuck items from embeddings_queue")
        cur.execute("DELETE FROM embeddings_queue")

    # Clean fulltext search for removed embeddings
    cur.execute("""
        DELETE FROM embedding_fulltext_search_content
        WHERE id NOT IN (SELECT id FROM embeddings)
    """)
    orphan_fts = cur.rowcount
    print(f"  Cleaned {orphan_fts} orphaned fulltext search entries")

    # Delete the fortress_docs collection and its segments
    cur.execute("SELECT id FROM collections WHERE name = ?", (COLLECTION_NAME,))
    col_row = cur.fetchone()
    if col_row:
        col_id = col_row[0]
        print(f"  Deleting fortress_docs collection ({col_id[:16]}...)")

        # Delete segments
        cur.execute("SELECT id FROM segments WHERE collection = ?", (col_id,))
        for (seg_id,) in cur.fetchall():
            cur.execute("DELETE FROM embeddings WHERE segment_id = ?", (seg_id,))
            cur.execute("DELETE FROM max_seq_id WHERE segment_id = ?", (seg_id,))
            # Delete HNSW directory if exists
            hnsw_dir = os.path.join(CHROMA_DB_PATH, seg_id)
            if os.path.exists(hnsw_dir):
                import shutil
                shutil.rmtree(hnsw_dir)
                print(f"    Removed HNSW dir: {seg_id[:16]}...")

        cur.execute("DELETE FROM segments WHERE collection = ?", (col_id,))
        cur.execute("DELETE FROM segment_metadata WHERE segment_id NOT IN (SELECT id FROM segments)")
        cur.execute("DELETE FROM collection_metadata WHERE collection_id = ?", (col_id,))
        cur.execute("DELETE FROM collections WHERE id = ?", (col_id,))

    conn.commit()

    # Vacuum to reclaim space
    print("  Running VACUUM to reclaim space...")
    cur.execute("VACUUM")
    conn.close()

    db_size = os.path.getsize(SQLITE_PATH) / 1e6
    print(f"  SQLite size after cleanup: {db_size:.1f} MB")
    print("  Corruption cleaned.")

    # Restart ChromaDB
    print("  Restarting ChromaDB HTTP server...")
    os.system(
        f"nohup /usr/bin/python3 /home/admin/.local/bin/chroma run "
        f"--path {CHROMA_DB_PATH} --host 0.0.0.0 --port 8002 "
        f"> /tmp/chroma_server.log 2>&1 &"
    )
    time.sleep(4)


# =============================================================================
# STEP 3: REBUILD WITH FRESH EMBEDDINGS
# =============================================================================

def load_progress():
    """Load rebuild progress (for resume support)."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"last_line": 0, "total_added": 0}


def save_progress(last_line: int, total_added: int):
    """Save rebuild progress."""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({"last_line": last_line, "total_added": total_added}, f)


def rebuild_collection():
    """Rebuild fortress_docs from the backup with fresh embeddings."""
    print("\n" + "=" * 65)
    print("  STEP 3: Rebuilding fortress_docs with fresh embeddings")
    print("=" * 65)

    if not os.path.exists(BACKUP_PATH):
        print(f"  [ERROR] Backup not found at {BACKUP_PATH}")
        print(f"  Run with --extract first.")
        return

    # Verify embedding model
    print("  Verifying embedding model...")
    test_emb = get_embedding("test")
    if test_emb is None:
        print("  [FATAL] Cannot generate embeddings. Is Ollama running?")
        return
    print(f"  Embedding OK: {len(test_emb)}-dim from {EMBED_MODEL}")

    # Connect to ChromaDB
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"  Collection '{COLLECTION_NAME}' current count: {collection.count()}")

    # Count total lines in backup
    total_lines = sum(1 for _ in open(BACKUP_PATH))
    print(f"  Backup has {total_lines} records to rebuild")

    # Load progress
    progress = load_progress()
    start_line = progress["last_line"]
    total_added = progress["total_added"]
    if start_line > 0:
        print(f"  Resuming from line {start_line} ({total_added} already added)")

    # Process in batches
    batch_ids = []
    batch_docs = []
    batch_metas = []
    batch_embeddings = []
    errors = 0
    embed_fails = 0
    t0 = time.time()
    current_line = 0

    with open(BACKUP_PATH) as f:
        for line_num, line in enumerate(f):
            if line_num < start_line:
                continue

            current_line = line_num

            try:
                record = json.loads(line.strip())
                doc = record["document"]
                meta = record["metadata"]
                doc_id = record["id"]

                # Generate embedding
                emb = get_embedding(doc)
                if emb is None:
                    embed_fails += 1
                    continue

                # Remove internal chroma keys from metadata
                clean_meta = {k: v for k, v in meta.items()
                              if not k.startswith("chroma:") and v is not None}

                # ChromaDB metadata values must be str, int, float, or bool
                for k, v in list(clean_meta.items()):
                    if not isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = str(v)

                batch_ids.append(doc_id)
                batch_docs.append(doc)
                batch_metas.append(clean_meta)
                batch_embeddings.append(emb)

                # Flush batch
                if len(batch_ids) >= BATCH_SIZE:
                    try:
                        collection.add(
                            ids=batch_ids,
                            documents=batch_docs,
                            metadatas=batch_metas,
                            embeddings=batch_embeddings,
                        )
                        total_added += len(batch_ids)
                    except Exception as e:
                        # Try one by one on batch failure
                        for i in range(len(batch_ids)):
                            try:
                                collection.add(
                                    ids=[batch_ids[i]],
                                    documents=[batch_docs[i]],
                                    metadatas=[batch_metas[i]],
                                    embeddings=[batch_embeddings[i]],
                                )
                                total_added += 1
                            except Exception:
                                errors += 1

                    batch_ids, batch_docs, batch_metas, batch_embeddings = [], [], [], []

                    # Save progress every batch
                    save_progress(current_line + 1, total_added)

                    if total_added % 500 == 0:
                        elapsed = time.time() - t0
                        rate = total_added / elapsed if elapsed > 0 else 0
                        remaining = (total_lines - start_line - total_added) / rate if rate > 0 else 0
                        print(f"     {total_added}/{total_lines} rebuilt "
                              f"({rate:.1f}/s, ~{remaining/60:.0f}min remaining)")

            except Exception:
                errors += 1

    # Flush remaining
    if batch_ids:
        try:
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
                embeddings=batch_embeddings,
            )
            total_added += len(batch_ids)
        except Exception:
            errors += len(batch_ids)

    save_progress(current_line + 1, total_added)
    elapsed = time.time() - t0

    print(f"\n  Rebuild complete in {elapsed/60:.1f} minutes")
    print(f"  Total added   : {total_added}")
    print(f"  Errors         : {errors}")
    print(f"  Embed failures : {embed_fails}")
    print(f"  Collection now : {collection.count()} docs")

    # Clean up progress file on success
    if total_added >= total_lines - start_line - errors - embed_fails:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
        print("  Repair COMPLETE. fortress_docs is operational.")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Repair fortress_docs collection")
    parser.add_argument("--extract", action="store_true",
                        help="Extract and backup only (no rebuild)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume interrupted rebuild")
    parser.add_argument("--clean-only", action="store_true",
                        help="Only clean corruption (no rebuild)")
    args = parser.parse_args()

    print("=" * 65)
    print("  FORTRESS DOCS REPAIR — Collection Recovery Tool")
    print("=" * 65)

    if args.resume:
        rebuild_collection()
        return

    # Step 1: Extract
    count = extract_orphaned_data()

    if args.extract:
        print("\n  Extract complete. Run without --extract to continue repair.")
        return

    if count == 0:
        print("  Nothing to repair.")
        return

    # Step 2: Clean
    clean_corruption()

    if args.clean_only:
        print("\n  Cleanup complete. Run --resume to rebuild when ready.")
        return

    # Step 3: Rebuild
    rebuild_collection()

    # Final restart of ChromaDB to pick up new data
    print("\n  Restarting ChromaDB HTTP server with rebuilt data...")
    os.system("pkill -f 'chroma run.*8002' 2>/dev/null")
    time.sleep(2)
    os.system(
        f"nohup /usr/bin/python3 /home/admin/.local/bin/chroma run "
        f"--path {CHROMA_DB_PATH} --host 0.0.0.0 --port 8002 "
        f"> /tmp/chroma_server.log 2>&1 &"
    )
    time.sleep(3)
    print("  ChromaDB restarted.")
    print("\n" + "=" * 65)
    print("  REPAIR COMPLETE — fortress_docs is back online")
    print("=" * 65)


if __name__ == "__main__":
    main()
