#!/usr/bin/env python3
"""
Fortress Prime - Garbage Collector
====================================
Content-based deduplication for ChromaDB vector collections.

Strategy:
  1. IDENTIFY via SQLite (zero RAM overhead — streams rows, never loads all vectors)
  2. GROUP by MD5 content hash
  3. KEEP the newest version per hash (by ingested_at timestamp)
  4. DELETE via ChromaDB API in safe batches
  5. LOG every deletion to NAS audit trail

Safety:
  - Dry-run mode by default (pass --execute to actually delete)
  - Backs up deletion manifest before purging
  - Batched deletes (41 vectors per batch — ChromaDB safe limit)
  - fortress_vision is excluded (already clean)

Usage:
    # Dry run (see what would be deleted)
    python3 tools/garbage_collector.py

    # Execute the purge
    python3 tools/garbage_collector.py --execute

    # Target a single collection
    python3 tools/garbage_collector.py --execute --collection fortress_docs
"""

import sqlite3
import hashlib
import json
import os
import sys
import argparse
import time
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────────────────

# ChromaDB — local NVMe (migrated from /mnt/ai_fast NFS 2026-02-10)
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import CHROMA_PATH
except ImportError:
    CHROMA_PATH = "/home/admin/fortress_fast/chroma_db"
CHROMA_SQLITE = os.path.join(CHROMA_PATH, "chroma.sqlite3")
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs/garbage_collector"

COLLECTIONS_TO_CLEAN = ["fortress_docs", "fortress_knowledge"]

# ChromaDB API delete batch size (conservative to avoid timeouts)
DELETE_BATCH_SIZE = 500

# SQLite scan batch size (rows fetched per iteration)
SCAN_BATCH_SIZE = 10_000


# ── Phase 1: Identify duplicates via SQLite ─────────────────────────────────

def get_segment_map(conn: sqlite3.Connection) -> dict:
    """Map collection names to their METADATA segment IDs."""
    cur = conn.execute("""
        SELECT c.name, s.id as segment_id
        FROM collections c
        JOIN segments s ON s.collection = c.id
        WHERE s.scope = 'METADATA'
    """)
    return {row[0]: row[1] for row in cur.fetchall()}


def scan_duplicates(conn: sqlite3.Connection, segment_id: str,
                    collection_name: str) -> tuple[list[str], dict]:
    """
    Scan a collection for content duplicates using MD5 hashing.
    Returns (ids_to_delete, stats_dict).

    Uses streaming reads — never loads all 157k vectors into RAM at once.
    """
    print(f"\n  [SCAN] Streaming '{collection_name}' for content hashing...")

    # Count total
    cur = conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE segment_id = ?", (segment_id,)
    )
    total = cur.fetchone()[0]
    print(f"    Total vectors: {total:,}")

    if total == 0:
        return [], {"total": 0, "unique": 0, "duplicates": 0}

    # Determine the timestamp metadata key for this collection
    ts_key = "ingested_at"  # both collections use this

    # Stream through all vectors, building content hash groups
    # Each group: hash -> [(embedding_id, timestamp), ...]
    content_groups = defaultdict(list)
    scanned = 0
    offset = 0

    while offset < total:
        # Fetch batch: embedding_id (string), document text, ingested_at timestamp
        cur = conn.execute("""
            SELECT
                e.embedding_id,
                doc.string_value AS doc_text,
                ts.string_value AS ingested_at
            FROM embeddings e
            LEFT JOIN embedding_metadata doc
                ON doc.id = e.id AND doc.key = 'chroma:document'
            LEFT JOIN embedding_metadata ts
                ON ts.id = e.id AND ts.key = ?
            WHERE e.segment_id = ?
            ORDER BY e.id
            LIMIT ? OFFSET ?
        """, (ts_key, segment_id, SCAN_BATCH_SIZE, offset))

        rows = cur.fetchall()
        if not rows:
            break

        for embedding_id, doc_text, ingested_at in rows:
            if doc_text:
                content_hash = hashlib.md5(doc_text.encode('utf-8')).hexdigest()
                content_groups[content_hash].append({
                    "embedding_id": embedding_id,
                    "ingested_at": ingested_at or "1970-01-01",
                })
            scanned += 1

        offset += SCAN_BATCH_SIZE
        print(f"    Scanned {min(offset, total):,}/{total:,}...", end="\r", flush=True)

    print(f"    Scanned {scanned:,}/{total:,} vectors                    ")

    # Identify garbage: for each hash group with >1 entry, keep newest, mark rest for deletion
    ids_to_delete = []
    duplicate_groups = 0

    for content_hash, entries in content_groups.items():
        if len(entries) > 1:
            # Sort by ingested_at descending — keep the newest
            entries.sort(key=lambda x: x["ingested_at"], reverse=True)
            # Keep entries[0], delete entries[1:]
            for entry in entries[1:]:
                ids_to_delete.append(entry["embedding_id"])
            duplicate_groups += 1

    unique_count = len(content_groups)
    dup_count = len(ids_to_delete)

    stats = {
        "total": total,
        "scanned": scanned,
        "unique": unique_count,
        "duplicates": dup_count,
        "duplicate_groups": duplicate_groups,
        "rate": (dup_count / total * 100) if total > 0 else 0,
        "final_size": total - dup_count,
    }

    print(f"    Unique content hashes: {unique_count:,}")
    print(f"    Duplicate vectors:     {dup_count:,} ({stats['rate']:.1f}%)")
    print(f"    Duplicate groups:      {duplicate_groups:,}")
    print(f"    After cleanup:         {stats['final_size']:,} vectors")

    return ids_to_delete, stats


# ── Phase 2: Delete via ChromaDB API ────────────────────────────────────────

def purge_collection(collection_name: str, ids_to_delete: list[str],
                     dry_run: bool = True) -> dict:
    """
    Delete duplicate vectors from a ChromaDB collection.
    Uses the ChromaDB Python API for safe, atomic deletions.
    """
    if not ids_to_delete:
        print(f"    Nothing to delete in '{collection_name}'.")
        return {"deleted": 0}

    if dry_run:
        print(f"\n  [DRY RUN] Would delete {len(ids_to_delete):,} vectors from '{collection_name}'.")
        print(f"    Pass --execute to perform the actual purge.")
        return {"deleted": 0, "dry_run": True}

    print(f"\n  [PURGE] Deleting {len(ids_to_delete):,} vectors from '{collection_name}'...")

    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(collection_name)

    before_count = collection.count()
    deleted = 0
    errors = 0
    start = time.time()

    total_batches = (len(ids_to_delete) + DELETE_BATCH_SIZE - 1) // DELETE_BATCH_SIZE

    for i in range(0, len(ids_to_delete), DELETE_BATCH_SIZE):
        batch = ids_to_delete[i:i + DELETE_BATCH_SIZE]
        batch_num = (i // DELETE_BATCH_SIZE) + 1

        try:
            collection.delete(ids=batch)
            deleted += len(batch)
            elapsed = time.time() - start
            rate = deleted / elapsed if elapsed > 0 else 0
            eta = (len(ids_to_delete) - deleted) / rate if rate > 0 else 0
            print(f"    Batch {batch_num}/{total_batches}: "
                  f"deleted {deleted:,}/{len(ids_to_delete):,} "
                  f"({rate:.0f}/sec, ETA {eta:.0f}s)", end="\r", flush=True)
        except Exception as e:
            errors += 1
            print(f"\n    [ERROR] Batch {batch_num} failed: {e}")
            # Continue with remaining batches
            continue

    after_count = collection.count()
    elapsed = time.time() - start

    print(f"\n    Purge complete in {elapsed:.1f}s")
    print(f"    Before: {before_count:,} | After: {after_count:,} | "
          f"Removed: {before_count - after_count:,}")

    if errors > 0:
        print(f"    [WARN] {errors} batch(es) had errors")

    return {
        "deleted": deleted,
        "errors": errors,
        "before": before_count,
        "after": after_count,
        "duration_sec": elapsed,
    }


# ── Logging ─────────────────────────────────────────────────────────────────

def save_manifest(collection_name: str, ids_to_delete: list[str],
                  stats: dict, dry_run: bool):
    """Save the deletion manifest for audit trail."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "dryrun" if dry_run else "executed"

    # Manifest (JSON summary)
    manifest_path = os.path.join(
        LOG_DIR, f"gc_{collection_name}_{timestamp}_{mode}.json"
    )
    manifest = {
        "collection": collection_name,
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "stats": stats,
        "ids_to_delete_count": len(ids_to_delete),
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    # Full ID list (for recovery if needed)
    ids_path = os.path.join(
        LOG_DIR, f"gc_{collection_name}_{timestamp}_{mode}_ids.txt"
    )
    with open(ids_path, "w") as f:
        for vid in ids_to_delete:
            f.write(vid + "\n")

    print(f"    Manifest: {manifest_path}")
    print(f"    ID list:  {ids_path}")

    return manifest_path


# ── Main ────────────────────────────────────────────────────────────────────

def run_gc(execute: bool = False, target_collection: str = None):
    """Main garbage collection entry point."""
    print()
    print("=" * 65)
    print("  FORTRESS PRIME - GARBAGE COLLECTOR")
    print("  Content-Based Deduplication Engine")
    print("=" * 65)
    print(f"  Time:       {datetime.now().isoformat()}")
    print(f"  ChromaDB:   {CHROMA_SQLITE}")
    print(f"  Mode:       {'EXECUTE (live purge)' if execute else 'DRY RUN (safe preview)'}")
    print(f"  Log dir:    {LOG_DIR}")

    if not os.path.exists(CHROMA_SQLITE):
        print(f"\n  [FATAL] Database not found: {CHROMA_SQLITE}")
        sys.exit(1)

    # Connect to SQLite for read-only scanning
    conn = sqlite3.connect(f"file:{CHROMA_SQLITE}?mode=ro", uri=True)
    segment_map = get_segment_map(conn)

    collections = [target_collection] if target_collection else COLLECTIONS_TO_CLEAN
    global_stats = {}
    global_deleted = 0

    for col_name in collections:
        if col_name not in segment_map:
            print(f"\n  [WARN] Collection '{col_name}' not found. Skipping.")
            continue

        segment_id = segment_map[col_name]

        print(f"\n{'─' * 65}")
        print(f"  COLLECTION: {col_name}")
        print(f"{'─' * 65}")

        # Phase 1: Identify
        ids_to_delete, stats = scan_duplicates(conn, segment_id, col_name)

        # Save manifest BEFORE deleting (safety net)
        if ids_to_delete:
            save_manifest(col_name, ids_to_delete, stats, dry_run=not execute)

        # Phase 2: Purge
        # Close read-only SQLite before opening ChromaDB client (avoids lock conflicts)
        if execute and ids_to_delete:
            conn.close()
            purge_result = purge_collection(col_name, ids_to_delete, dry_run=False)
            stats["purge"] = purge_result
            global_deleted += purge_result.get("deleted", 0)
            # Reopen for next collection
            conn = sqlite3.connect(f"file:{CHROMA_SQLITE}?mode=ro", uri=True)
            segment_map = get_segment_map(conn)
        else:
            purge_collection(col_name, ids_to_delete, dry_run=True)

        global_stats[col_name] = stats

    conn.close()

    # ── Summary ──
    print(f"\n{'=' * 65}")
    print(f"  GARBAGE COLLECTION COMPLETE")
    print(f"{'=' * 65}")

    total_dupes = sum(s.get("duplicates", 0) for s in global_stats.values())
    total_kept = sum(s.get("final_size", 0) for s in global_stats.values())

    for col_name, stats in global_stats.items():
        print(f"\n  {col_name}:")
        print(f"    Before:  {stats['total']:,} vectors")
        print(f"    Dupes:   {stats['duplicates']:,} ({stats['rate']:.1f}%)")
        print(f"    After:   {stats['final_size']:,} vectors")

    print(f"\n  TOTALS:")
    print(f"    Duplicates identified: {total_dupes:,}")
    if execute:
        print(f"    Vectors deleted:       {global_deleted:,}")
        print(f"    Remaining vectors:     {total_kept:,}")
        print(f"\n  The Brain has been cleaned. Run the audit to verify:")
        print(f"    python3 tools/audit_cortex.py")
    else:
        print(f"    Vectors to delete:     {total_dupes:,}")
        print(f"    Projected remaining:   {total_kept:,}")
        print(f"\n  This was a DRY RUN. To execute the purge:")
        print(f"    python3 tools/garbage_collector.py --execute")

    print(f"\n{'=' * 65}\n")


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fortress Prime - Garbage Collector (Content-Based Deduplication)"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually delete duplicates (default is dry-run)"
    )
    parser.add_argument(
        "--collection", type=str, default=None,
        help="Target a specific collection (default: all configured)"
    )
    args = parser.parse_args()

    run_gc(execute=args.execute, target_collection=args.collection)
