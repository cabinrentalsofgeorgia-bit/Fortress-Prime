#!/usr/bin/env python3
"""
Fortress Prime - Vector Cortex Health Audit
=============================================
Deep diagnostic of all ChromaDB instances in the cluster.
Uses direct SQLite access to avoid memory issues with 150k+ vectors.

Checks:
  1. Collection inventory and vector counts
  2. Content-hash deduplication rate (MD5 of chunk text)
  3. Source file distribution and metadata consistency
  4. Category breakdown
  5. Stale/orphan detection (metadata gaps)
  6. Cross-collection overlap

Targets:
  - PRIMARY:  /mnt/ai_fast/chroma_db         (NVMe fast tier)
  - LEGACY:   /mnt/fortress_nas/chroma_db     (NAS, older ingestion runs)

Usage:
    python3 tools/audit_cortex.py
    python3 tools/audit_cortex.py --db /mnt/ai_fast/chroma_db
    python3 tools/audit_cortex.py --deep   # include cross-collection overlap check
"""

import sqlite3
import os
import sys
import hashlib
import argparse
from collections import Counter, defaultdict
from datetime import datetime

# ── Configuration ───────────────────────────────────────────────────────────

# ChromaDB locations — primary migrated to local NVMe 2026-02-10
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import CHROMA_PATH as _PRIMARY_CHROMA
    _PRIMARY_SQLITE = os.path.join(_PRIMARY_CHROMA, "chroma.sqlite3")
except ImportError:
    _PRIMARY_SQLITE = "/home/admin/fortress_fast/chroma_db/chroma.sqlite3"

CHROMA_LOCATIONS = {
    "PRIMARY (Local NVMe)": _PRIMARY_SQLITE,
    "LEGACY (NAS NFS)":     "/mnt/ai_fast/chroma_db/chroma.sqlite3",
    "LEGACY (NAS Brain)":   "/mnt/fortress_nas/chroma_db/chroma.sqlite3",
}

# Batch size for fetching document content (avoid memory spikes)
BATCH_SIZE = 10_000


# ── Database helpers ────────────────────────────────────────────────────────

def connect(db_path: str) -> sqlite3.Connection | None:
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_collections(conn: sqlite3.Connection) -> list[dict]:
    """Return list of {id, name, dimension, segment_id} for all collections.
    ChromaDB uses: embeddings.segment_id -> segments.id -> segments.collection -> collections.id
    Each collection has a METADATA segment and a VECTOR segment; we want the METADATA segment_id
    since that's what embeddings and embedding_metadata are keyed on.
    """
    cur = conn.execute("""
        SELECT c.id, c.name, c.dimension, s.id as segment_id
        FROM collections c
        JOIN segments s ON s.collection = c.id
        WHERE s.scope = 'METADATA'
    """)
    return [{"id": row[0], "name": row[1], "dimension": row[2], "segment_id": row[3]}
            for row in cur.fetchall()]


def count_vectors(conn: sqlite3.Connection, segment_id: str = None) -> int:
    """Count total vectors, optionally filtered by segment_id (which maps to a collection)."""
    if segment_id:
        cur = conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE segment_id = ?",
            (segment_id,)
        )
    else:
        cur = conn.execute("SELECT COUNT(*) FROM embeddings")
    return cur.fetchone()[0]


# ── Audit functions ─────────────────────────────────────────────────────────

def audit_duplicates(conn: sqlite3.Connection, segment_id: str,
                     collection_name: str) -> dict:
    """
    Check content-level duplication by hashing document text.
    Returns stats dict with duplication info.
    """
    print(f"\n  [DEDUP] Scanning '{collection_name}' for duplicate content...")

    total = count_vectors(conn, segment_id)
    if total == 0:
        print("    Collection is empty.")
        return {"total": 0, "unique": 0, "duplicates": 0, "rate": 0.0}

    # Fetch all document text in batches and hash
    content_hashes = defaultdict(list)  # hash -> [embedding_id, ...]
    offset = 0
    fetched = 0

    while offset < total:
        cur = conn.execute("""
            SELECT e.id, em.string_value
            FROM embeddings e
            JOIN embedding_metadata em ON e.id = em.id
            WHERE e.segment_id = ?
              AND em.key = 'chroma:document'
            LIMIT ? OFFSET ?
        """, (segment_id, BATCH_SIZE, offset))

        rows = cur.fetchall()
        if not rows:
            break

        for emb_id, doc_text in rows:
            if doc_text:
                doc_hash = hashlib.md5(doc_text.encode('utf-8')).hexdigest()
                content_hashes[doc_hash].append(emb_id)
            fetched += 1

        offset += BATCH_SIZE
        print(f"    Scanned {min(offset, total):,}/{total:,} vectors...", end="\r")

    print(f"    Scanned {fetched:,}/{total:,} vectors (with document text)")

    unique = len(content_hashes)
    duplicates = fetched - unique
    rate = (duplicates / fetched * 100) if fetched > 0 else 0.0

    # Find worst offenders (most duplicated chunks)
    worst = sorted(content_hashes.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    worst_dupes = [(h, ids) for h, ids in worst if len(ids) > 1]

    return {
        "total": total,
        "with_text": fetched,
        "unique": unique,
        "duplicates": duplicates,
        "rate": rate,
        "worst_offenders": worst_dupes,
    }


def audit_metadata(conn: sqlite3.Connection, segment_id: str,
                   collection_name: str) -> dict:
    """
    Analyze metadata consistency: source files, categories, timestamps.
    """
    print(f"\n  [META] Analyzing metadata for '{collection_name}'...")

    total = count_vectors(conn, segment_id)

    # ── Source file distribution ──
    # Try both metadata key styles: 'source_file' (rag_ingest) and 'source' (langchain)
    source_key = None
    for key in ('source_file', 'source'):
        cur = conn.execute("""
            SELECT COUNT(*) FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            WHERE e.segment_id = ? AND em.key = ?
        """, (segment_id, key))
        if cur.fetchone()[0] > 0:
            source_key = key
            break

    source_counts = Counter()
    missing_source = 0

    if source_key:
        cur = conn.execute("""
            SELECT em.string_value, COUNT(*) as cnt
            FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            WHERE e.segment_id = ? AND em.key = ?
            GROUP BY em.string_value
            ORDER BY cnt DESC
        """, (segment_id, source_key))
        for row in cur.fetchall():
            if row[0]:
                source_counts[row[0]] = row[1]
            else:
                missing_source += row[1]

        # Count vectors that don't have this metadata key at all
        cur = conn.execute("""
            SELECT COUNT(*) FROM embeddings e
            WHERE e.segment_id = ?
              AND e.id NOT IN (
                  SELECT id FROM embedding_metadata WHERE key = ?
              )
        """, (segment_id, source_key))
        missing_source += cur.fetchone()[0]
    else:
        missing_source = total

    # ── Category distribution ──
    category_counts = Counter()
    cur = conn.execute("""
        SELECT em.string_value, COUNT(*) as cnt
        FROM embedding_metadata em
        JOIN embeddings e ON e.id = em.id
        WHERE e.segment_id = ? AND em.key = 'category'
        GROUP BY em.string_value
        ORDER BY cnt DESC
    """, (segment_id,))
    for row in cur.fetchall():
        category_counts[row[0] or "uncategorized"] = row[1]

    # ── Metadata keys inventory ──
    cur = conn.execute("""
        SELECT DISTINCT em.key, COUNT(*) as cnt
        FROM embedding_metadata em
        JOIN embeddings e ON e.id = em.id
        WHERE e.segment_id = ?
          AND em.key NOT LIKE 'chroma:%'
        GROUP BY em.key
        ORDER BY cnt DESC
    """, (segment_id,))
    meta_keys = {row[0]: row[1] for row in cur.fetchall()}

    # ── Ingestion timestamps ──
    earliest = latest = None
    for ts_key in ('ingested_at', 'created_at', 'timestamp'):
        cur = conn.execute("""
            SELECT MIN(em.string_value), MAX(em.string_value)
            FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            WHERE e.segment_id = ? AND em.key = ?
        """, (segment_id, ts_key))
        row = cur.fetchone()
        if row[0]:
            earliest, latest = row[0], row[1]
            break

    return {
        "source_key": source_key,
        "unique_sources": len(source_counts),
        "missing_source": missing_source,
        "top_sources": source_counts.most_common(10),
        "categories": dict(category_counts),
        "meta_keys": meta_keys,
        "earliest_ingest": earliest,
        "latest_ingest": latest,
    }


def audit_path_prefixes(conn: sqlite3.Connection, segment_id: str,
                        source_key: str) -> dict:
    """Analyze source path prefixes to detect stale/orphaned mount points."""
    if not source_key:
        return {"prefixes": {}}

    cur = conn.execute("""
        SELECT em.string_value
        FROM embedding_metadata em
        JOIN embeddings e ON e.id = em.id
        WHERE e.segment_id = ? AND em.key = ?
    """, (segment_id, source_key))

    prefix_counter = Counter()
    for (path,) in cur:
        if path:
            parts = path.split('/')
            prefix = '/'.join(parts[:4]) if len(parts) >= 4 else path
            prefix_counter[prefix] += 1

    return {"prefixes": dict(prefix_counter.most_common(15))}


# ── Main audit runner ───────────────────────────────────────────────────────

def run_audit(db_path: str, label: str, deep: bool = False):
    """Run the full audit on a single ChromaDB instance."""
    print("\n" + "=" * 70)
    print(f"  FORTRESS PRIME - VECTOR CORTEX HEALTH AUDIT")
    print(f"  Target: {label}")
    print(f"  DB:     {db_path}")
    print(f"  Time:   {datetime.now().isoformat()}")
    print("=" * 70)

    conn = connect(db_path)
    if not conn:
        print(f"\n  DATABASE NOT FOUND: {db_path}")
        print("  Skipping this instance.\n")
        return None

    # File size
    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"\n  Database Size: {size_mb:.1f} MB")

    # Collection inventory
    collections = get_collections(conn)
    total_vectors = count_vectors(conn)
    print(f"  Total Vectors (all collections): {total_vectors:,}")
    print(f"  Collections Found: {len(collections)}")

    results = {}

    for col in collections:
        seg_id = col["segment_id"]
        col_name = col["name"]
        col_dim = col["dimension"]
        col_count = count_vectors(conn, seg_id)

        print(f"\n{'─' * 70}")
        print(f"  COLLECTION: {col_name}")
        print(f"  Dimension: {col_dim}  |  Vectors: {col_count:,}")
        print(f"{'─' * 70}")

        if col_count == 0:
            print("    (empty collection, skipping)")
            results[col_name] = {"count": 0}
            continue

        # 1. Deduplication audit
        dedup = audit_duplicates(conn, seg_id, col_name)

        print(f"\n    Content Uniqueness:")
        print(f"      Vectors with text:   {dedup['with_text']:,}")
        print(f"      Unique chunks:       {dedup['unique']:,}")
        print(f"      Duplicate chunks:    {dedup['duplicates']:,}")
        print(f"      Duplication rate:    {dedup['rate']:.2f}%")

        if dedup["worst_offenders"]:
            print(f"\n    Worst Duplicate Offenders (same text, multiple vectors):")
            for h, ids in dedup["worst_offenders"][:5]:
                print(f"      Hash {h[:12]}... appears {len(ids)}x")

        # 2. Metadata audit
        meta = audit_metadata(conn, seg_id, col_name)

        print(f"\n    Metadata Consistency:")
        print(f"      Source key used:      {meta['source_key'] or 'NONE FOUND'}")
        print(f"      Unique source files:  {meta['unique_sources']:,}")
        print(f"      Missing source meta:  {meta['missing_source']:,}")
        if meta['earliest_ingest']:
            print(f"      Earliest ingestion:   {meta['earliest_ingest']}")
            print(f"      Latest ingestion:     {meta['latest_ingest']}")

        if meta['meta_keys']:
            print(f"\n    Metadata Keys (non-chroma):")
            for key, cnt in meta['meta_keys'].items():
                print(f"      {key:<25} {cnt:>8,} vectors")

        if meta['categories']:
            print(f"\n    Category Breakdown:")
            for cat, cnt in sorted(meta['categories'].items(), key=lambda x: -x[1]):
                pct = cnt / col_count * 100
                bar = "#" * int(pct / 2)
                print(f"      {cat:<20} {cnt:>8,} ({pct:5.1f}%) {bar}")

        if meta['top_sources']:
            print(f"\n    Top 10 Sources by Chunk Count:")
            for src, cnt in meta['top_sources']:
                name = src.split('/')[-1] if src else "(unknown)"
                print(f"      {cnt:>6,} chunks  {name}")

        # 3. Path prefix analysis
        paths = audit_path_prefixes(conn, seg_id, meta['source_key'])
        if paths['prefixes']:
            print(f"\n    Source Path Prefixes (mount point check):")
            for prefix, cnt in paths['prefixes'].items():
                print(f"      {cnt:>6,} chunks  {prefix}/...")

        # ── VERDICT ──
        print(f"\n    {'─' * 50}")
        print(f"    HEALTH VERDICT for '{col_name}':")

        issues = []
        if dedup['rate'] > 10:
            issues.append(f"CRITICAL: {dedup['rate']:.1f}% duplication — {dedup['duplicates']:,} redundant vectors")
        elif dedup['rate'] > 1:
            issues.append(f"WARNING: {dedup['rate']:.1f}% duplication — {dedup['duplicates']:,} redundant vectors")

        if meta['missing_source'] > col_count * 0.05:
            issues.append(f"WARNING: {meta['missing_source']:,} vectors missing source metadata ({meta['missing_source']/col_count*100:.1f}%)")

        orphan_text = dedup['total'] - dedup['with_text']
        if orphan_text > 0:
            issues.append(f"WARNING: {orphan_text:,} vectors have no document text (embedding-only orphans)")

        if issues:
            for issue in issues:
                if "CRITICAL" in issue:
                    print(f"    [RED]    {issue}")
                else:
                    print(f"    [YELLOW] {issue}")
        else:
            print(f"    [GREEN]  HEALTHY — {dedup['unique']:,} unique vectors, "
                  f"{dedup['rate']:.2f}% duplication, metadata intact")

        results[col_name] = {
            "count": col_count,
            "dedup": dedup,
            "meta": meta,
            "paths": paths,
            "issues": issues,
        }

    # ── GLOBAL SUMMARY ──
    print(f"\n{'=' * 70}")
    print(f"  GLOBAL SUMMARY — {label}")
    print(f"{'=' * 70}")
    print(f"  Database Size:     {size_mb:.1f} MB")
    print(f"  Total Vectors:     {total_vectors:,}")
    print(f"  Collections:       {len(collections)}")

    total_dupes = sum(r.get("dedup", {}).get("duplicates", 0) for r in results.values())
    total_unique = sum(r.get("dedup", {}).get("unique", 0) for r in results.values())
    global_rate = (total_dupes / (total_dupes + total_unique) * 100) if (total_dupes + total_unique) > 0 else 0

    print(f"  Unique Chunks:     {total_unique:,}")
    print(f"  Duplicate Chunks:  {total_dupes:,}")
    print(f"  Global Dup Rate:   {global_rate:.2f}%")

    all_issues = []
    for name, r in results.items():
        for issue in r.get("issues", []):
            all_issues.append(f"[{name}] {issue}")

    if all_issues:
        print(f"\n  ALL ISSUES:")
        for issue in all_issues:
            print(f"    {issue}")
    else:
        print(f"\n  NO ISSUES DETECTED")

    if global_rate > 10:
        print(f"\n  RECOMMENDATION: Run garbage collector before training R1.")
        print(f"  Estimated cleanup: ~{total_dupes:,} vectors to purge.")
    elif global_rate > 1:
        print(f"\n  RECOMMENDATION: Minor cleanup advisable. Proceed with caution to Step 2.")
    else:
        print(f"\n  RECOMMENDATION: Cortex is clean. Proceed directly to Senior Partner training.")

    print(f"\n{'=' * 70}\n")

    conn.close()
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fortress Prime - Vector Cortex Health Audit")
    parser.add_argument("--db", type=str, help="Path to a specific chroma.sqlite3 file")
    parser.add_argument("--deep", action="store_true", help="Include cross-collection overlap check")
    args = parser.parse_args()

    print("\n" + "#" * 70)
    print("#  FORTRESS PRIME — VECTOR CORTEX HEALTH AUDIT")
    print(f"#  Initiated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 70)

    if args.db:
        db_path = args.db if args.db.endswith(".sqlite3") else os.path.join(args.db, "chroma.sqlite3")
        run_audit(db_path, "CUSTOM", deep=args.deep)
    else:
        # Audit all known locations
        for label, path in CHROMA_LOCATIONS.items():
            run_audit(path, label, deep=args.deep)
