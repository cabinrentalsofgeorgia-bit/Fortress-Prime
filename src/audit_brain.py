"""
FORTRESS PRIME — Full System Audit ("The Delta")
==================================================
Scans every storage tier, counts every file by type, compares against
the indexed knowledge in ChromaDB and the Financial Vault.

Question: Total Data Available - Data Ingested = The Blind Spot

Usage:
    python3 src/audit_brain.py
"""

import os
import sys
import time
import sqlite3
import psycopg2
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# ── Load environment ──
load_dotenv(Path(__file__).parent.parent / ".env")

# =============================================================================
# CONFIGURATION
# =============================================================================

# All NAS scan targets (every mounted volume that could contain data)
SCAN_TARGETS = {
    # ── Tier 1: NVMe (Fast) ──
    "NVMe Fast (/mnt/ai_fast)":       "/mnt/ai_fast",
    # ── Tier 2: Brain (NVMe) ──
    "NAS Brain (/mnt/fortress_nas)":   "/mnt/fortress_nas",
    # ── Tier 3: HDD Bulk ──
    "HDD Bulk (/mnt/ai_bulk)":        "/mnt/ai_bulk",
    # ── Vol1 Source Shares (the raw empire) ──
    "Vol1 Photos":                     "/mnt/vol1_source/Personal/Photos",
    "Vol1 Documents":                  "/mnt/vol1_source/Personal/Documents",
    "Vol1 Video Library":              "/mnt/vol1_source/Personal/Video_Library",
    "Vol1 Properties":                 "/mnt/vol1_source/Properties",
    "Vol1 Business":                   "/mnt/vol1_source/Business",
    "CROG Workspace":                  "/mnt/crog_workspace",
}

# File type buckets
EXT_MAP = {
    "PDF":       {"pdf"},
    "DOC/TXT":   {"doc", "docx", "txt", "md", "rtf", "odt", "pages", "csv", "xlsx", "xls"},
    "IMAGES":    {"jpg", "jpeg", "png", "heic", "webp", "tiff", "tif", "gif", "bmp", "raw", "cr2", "nef", "arw", "dng"},
    "VIDEO":     {"mp4", "mov", "avi", "mkv", "m4v", "wmv", "flv", "webm", "mpg", "mpeg", "3gp"},
    "AUDIO":     {"mp3", "wav", "aac", "flac", "ogg", "m4a", "wma"},
    "EMAIL":     {"eml", "msg", "mbox"},
    "CODE":      {"py", "js", "ts", "html", "css", "json", "yaml", "yml", "sh", "sql", "xml"},
    "ARCHIVE":   {"zip", "tar", "gz", "rar", "7z", "bz2", "dmg", "iso"},
}

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

# ChromaDB — local NVMe (migrated from /mnt/ai_fast NFS 2026-02-10)
try:
    from src.fortress_paths import CHROMA_PATH
except ImportError:
    CHROMA_PATH = "/home/admin/fortress_fast/chroma_db"


# =============================================================================
# SCANNER
# =============================================================================

def classify_ext(ext: str) -> str:
    """Classify a file extension into a bucket."""
    ext = ext.lower().lstrip(".")
    for bucket, extensions in EXT_MAP.items():
        if ext in extensions:
            return bucket
    return "OTHER"


def scan_storage(path: str, label: str) -> dict:
    """Walk a directory tree, counting files by type and total size."""
    stats = defaultdict(lambda: {"count": 0, "size": 0})
    total_files = 0
    total_bytes = 0
    errors = 0

    if not os.path.exists(path):
        print(f"   SKIP  {label} — path does not exist: {path}")
        return {"stats": dict(stats), "total_files": 0, "total_bytes": 0, "errors": 0}

    sys.stdout.write(f"   SCAN  {label}...")
    sys.stdout.flush()
    start = time.time()

    for root, dirs, files in os.walk(path, followlinks=False):
        # Skip recycle bins and system dirs
        dirs[:] = [d for d in dirs if d not in ("#recycle", "@eaDir", ".Trash-1000", "@tmp", ".git")]
        for f in files:
            try:
                fpath = os.path.join(root, f)
                ext = f.rsplit(".", 1)[-1] if "." in f else ""
                bucket = classify_ext(ext)
                try:
                    fsize = os.path.getsize(fpath)
                except (PermissionError, OSError):
                    fsize = 0

                stats[bucket]["count"] += 1
                stats[bucket]["size"] += fsize
                total_files += 1
                total_bytes += fsize
            except (PermissionError, OSError):
                errors += 1

            # Progress tick every 10,000 files
            if total_files % 10000 == 0:
                sys.stdout.write(f" {total_files // 1000}k")
                sys.stdout.flush()

    elapsed = time.time() - start
    print(f"         Done. {total_files:,} files ({total_bytes / (1024**3):.2f} GB) in {elapsed:.1f}s")
    if errors:
        print(f"         ({errors} files skipped due to permission errors)")

    return {
        "stats": dict(stats),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "errors": errors,
    }


# =============================================================================
# COGNITIVE AUDIT (ChromaDB)
# =============================================================================

def audit_chromadb() -> dict:
    """Check all ChromaDB collections for vector counts."""
    print("\n   SCAN  Legal Cortex (ChromaDB)...")
    result = {"collections": {}, "total_vectors": 0, "status": "OFFLINE"}

    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collections = client.list_collections()
        total = 0
        for col in collections:
            count = col.count()
            result["collections"][col.name] = count
            total += count
            print(f"         {col.name}: {count:,} vectors")

        result["total_vectors"] = total
        result["status"] = "ONLINE"
        print(f"         TOTAL: {total:,} vectors indexed")
    except Exception as e:
        print(f"         ChromaDB client error: {e}")
        print(f"         Falling back to direct SQLite read...")
        result = _audit_chromadb_sqlite_fallback()

    return result


def _audit_chromadb_sqlite_fallback() -> dict:
    """Read ChromaDB counts directly from SQLite (bypasses Rust client bug)."""
    result = {"collections": {}, "total_vectors": 0, "status": "DEGRADED"}

    db_path = os.path.join(CHROMA_PATH, "chroma.sqlite3")
    if not os.path.exists(db_path):
        print(f"         SQLite file not found: {db_path}")
        return result

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Map collections
        cur.execute("SELECT id, name FROM collections")
        colmap = {r[0]: r[1] for r in cur.fetchall()}

        # Map segments to collections
        cur.execute("SELECT id, collection, scope FROM segments")
        segmap = {}
        for seg_id, col_id, scope in cur.fetchall():
            segmap[seg_id] = (colmap.get(col_id, "unknown"), scope)

        # Count embeddings per metadata segment
        cur.execute("SELECT segment_id, count(*) FROM embeddings GROUP BY segment_id")
        total = 0
        for seg_id, count in cur.fetchall():
            col_name, scope = segmap.get(seg_id, ("unknown", "unknown"))
            if col_name not in result["collections"]:
                result["collections"][col_name] = 0
            result["collections"][col_name] += count
            total += count
            print(f"         {col_name}: {count:,} embeddings ({scope})")

        # Check write queue
        cur.execute("SELECT count(*) FROM embeddings_queue")
        queued = cur.fetchone()[0]
        if queued:
            total += queued
            print(f"         (+ {queued:,} in write queue)")

        result["total_vectors"] = total
        result["status"] = "DEGRADED"
        print(f"         TOTAL: {total:,} (via SQLite fallback — HNSW index needs repair)")
        conn.close()
    except Exception as e2:
        print(f"         SQLite fallback also failed: {e2}")

    return result


# =============================================================================
# FINANCIAL VAULT AUDIT (PostgreSQL)
# =============================================================================

def audit_postgres() -> dict:
    """Check all critical PostgreSQL tables for row counts."""
    print("\n   SCAN  Financial Vault (PostgreSQL)...")
    result = {"tables": {}, "status": "OFFLINE"}

    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        # Critical tables to audit
        critical_tables = [
            ("ops_properties", "Tracked Assets (Cabins)"),
            ("fin_reservations", "Reservation Ledger"),
            ("revenue_ledger", "Revenue Engine Entries"),
            ("general_ledger", "Financial Documents"),
            ("asset_docs", "Asset Document Index"),
            ("maintenance_log", "Vision Inspections"),
            ("ops_tasks", "Operations Tasks"),
            ("ops_turnovers", "Turnover Events"),
            ("ops_crew", "Field Operatives"),
            ("images", "Processed Images (Legacy)"),
            ("ops_visuals", "Vision Engine (The Eye)"),
            ("vision_runs", "Vision Ingestion Runs"),
            ("properties", "Property Master List"),
            ("legal_matters", "Legal Cases"),
        ]

        for table, label in critical_tables:
            try:
                cur.execute(f"SELECT count(*) FROM {table}")
                count = cur.fetchone()[0]
                result["tables"][table] = {"count": count, "label": label}
                print(f"         {label}: {count:,}")
            except Exception:
                conn.rollback()
                result["tables"][table] = {"count": 0, "label": label, "error": "table missing"}

        # Vision pipeline detail
        try:
            cur.execute("""
                SELECT status, count(*) FROM ops_visuals GROUP BY status ORDER BY count(*) DESC
            """)
            result["vision_status_breakdown"] = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT COALESCE(property_name, '** UNMATCHED **') as prop, count(*) as cnt
                FROM ops_visuals WHERE status = 'DONE'
                GROUP BY property_name ORDER BY cnt DESC LIMIT 15
            """)
            result["vision_property_coverage"] = [(r[0], r[1]) for r in cur.fetchall()]

            cur.execute("""
                SELECT run_id, scan_path, images_found, images_processed, images_failed, status
                FROM vision_runs ORDER BY run_id
            """)
            result["vision_runs"] = [
                {"run_id": r[0], "path": r[1], "found": r[2], "processed": r[3],
                 "failed": r[4] or 0, "status": r[5]}
                for r in cur.fetchall()
            ]
        except Exception:
            conn.rollback()

        result["status"] = "ONLINE"
        conn.close()
    except Exception as e:
        print(f"         PostgreSQL ERROR: {e}")
        result["error"] = str(e)

    return result


# =============================================================================
# THE EXECUTIVE SUMMARY
# =============================================================================

def print_executive_summary(scan_results: dict, chroma: dict, postgres: dict):
    """Print the full gap analysis."""

    # Aggregate across all scan targets
    grand_totals = defaultdict(lambda: {"count": 0, "size": 0})
    grand_files = 0
    grand_bytes = 0

    for label, result in scan_results.items():
        grand_files += result["total_files"]
        grand_bytes += result["total_bytes"]
        for bucket, data in result["stats"].items():
            grand_totals[bucket]["count"] += data["count"]
            grand_totals[bucket]["size"] += data["size"]

    vector_count = chroma.get("total_vectors", 0)

    # ── Header ──
    print("\n")
    print("=" * 72)
    print("  FORTRESS PRIME — EXECUTIVE INTELLIGENCE AUDIT")
    print("  \"What does the Brain know vs. what exists?\"")
    print("=" * 72)

    # ── Physical Assets ──
    print(f"\n  PHYSICAL STORAGE INVENTORY")
    print(f"  {'─' * 66}")
    print(f"  {'Category':<20} {'Files':>12} {'Size':>12}")
    print(f"  {'─' * 66}")

    # Sort by count descending
    for bucket in sorted(grand_totals.keys(), key=lambda b: grand_totals[b]["count"], reverse=True):
        data = grand_totals[bucket]
        size_str = f"{data['size'] / (1024**3):.2f} GB" if data['size'] > 1024**3 else f"{data['size'] / (1024**2):.1f} MB"
        print(f"  {bucket:<20} {data['count']:>12,} {size_str:>12}")

    print(f"  {'─' * 66}")
    print(f"  {'TOTAL':<20} {grand_files:>12,} {grand_bytes / (1024**3):>10.2f} GB")

    # ── Per-Target Breakdown ──
    print(f"\n  BREAKDOWN BY STORAGE TIER")
    print(f"  {'─' * 66}")
    for label, result in sorted(scan_results.items(), key=lambda x: x[1]["total_files"], reverse=True):
        if result["total_files"] > 0:
            gb = result["total_bytes"] / (1024**3)
            # Show top file types for this target
            top_types = sorted(result["stats"].items(), key=lambda x: x[1]["count"], reverse=True)[:3]
            top_str = ", ".join(f"{b}:{d['count']:,}" for b, d in top_types)
            print(f"  {label:<42} {result['total_files']:>8,} files  ({gb:>7.2f} GB)")
            print(f"  {'':>4}Top: {top_str}")

    # ── Cognitive Layer ──
    print(f"\n\n  COGNITIVE LAYER — WHAT THE BRAIN KNOWS")
    print(f"  {'─' * 66}")

    # Text Intelligence
    text_available = grand_totals.get("PDF", {}).get("count", 0) + grand_totals.get("DOC/TXT", {}).get("count", 0)
    text_status = "GREEN" if vector_count > 50000 else ("AMBER" if vector_count > 10000 else "RED")
    print(f"\n  TEXT INTELLIGENCE:")
    print(f"    Documents on NAS:       {text_available:>10,}")
    print(f"    Vectors in ChromaDB:    {vector_count:>10,}")
    est_pages = int(vector_count / 5) if vector_count else 0
    print(f"    Est. pages indexed:     {est_pages:>10,} (~{vector_count}/5 chunks)")
    print(f"    Status:                 [{text_status}]")

    # Visual Intelligence (Division 6 — The Eye)
    img_count = grand_totals.get("IMAGES", {}).get("count", 0)
    img_size = grand_totals.get("IMAGES", {}).get("size", 0)
    img_legacy = postgres.get("tables", {}).get("images", {}).get("count", 0)
    img_eye = postgres.get("tables", {}).get("ops_visuals", {}).get("count", 0)
    maint_inspections = postgres.get("tables", {}).get("maintenance_log", {}).get("count", 0)
    vision_runs_count = postgres.get("tables", {}).get("vision_runs", {}).get("count", 0)
    img_total = img_legacy + img_eye
    vision_pct = (img_total / img_count * 100) if img_count > 0 else 0
    vision_status = "GREEN" if vision_pct > 50 else ("AMBER" if img_total > 100 else "RED")
    print(f"\n  VISUAL INTELLIGENCE (Division 6 — The Eye):")
    print(f"    Images on NAS:          {img_count:>10,} ({img_size / (1024**3):.2f} GB)")
    print(f"    Seen by The Eye:        {img_eye:>10,}")
    print(f"    Processed (Legacy):     {img_legacy:>10,}")
    print(f"    Coverage:               {vision_pct:>9.2f}%")
    print(f"    Maintenance inspections:{maint_inspections:>10,}")
    print(f"    Ingestion runs:         {vision_runs_count:>10,}")
    print(f"    Vision engine:          {'ACTIVE' if img_eye > 50 else ('WARMING UP' if img_eye > 0 else 'OFFLINE')}")
    print(f"    Status:                 [{vision_status}]")

    # Video Intelligence
    vid_count = grand_totals.get("VIDEO", {}).get("count", 0)
    vid_size = grand_totals.get("VIDEO", {}).get("size", 0)
    print(f"\n  VIDEO INTELLIGENCE:")
    print(f"    Videos on NAS:          {vid_count:>10,} ({vid_size / (1024**3):.2f} GB)")
    print(f"    Videos processed:       {0:>10,}")
    print(f"    Status:                 [RED]")

    # Financial Intelligence
    res_count = postgres.get("tables", {}).get("fin_reservations", {}).get("count", 0)
    rev_entries = postgres.get("tables", {}).get("revenue_ledger", {}).get("count", 0)
    gl_count = postgres.get("tables", {}).get("general_ledger", {}).get("count", 0)
    prop_count = postgres.get("tables", {}).get("ops_properties", {}).get("count", 0)
    asset_count = postgres.get("tables", {}).get("asset_docs", {}).get("count", 0)
    fin_status = "GREEN" if gl_count > 10000 else ("AMBER" if gl_count > 100 else "RED")
    print(f"\n  FINANCIAL INTELLIGENCE:")
    print(f"    General ledger entries: {gl_count:>10,}")
    print(f"    Asset doc index:        {asset_count:>10,}")
    print(f"    Reservation records:    {res_count:>10,}")
    print(f"    Revenue engine entries: {rev_entries:>10,}")
    print(f"    Tracked properties:     {prop_count:>10,}")
    print(f"    Status:                 [{fin_status}]")

    # ── VISION PIPELINE DETAIL ──
    vision_props = postgres.get("vision_property_coverage", [])
    vision_breakdown = postgres.get("vision_status_breakdown", {})
    vision_runs_data = postgres.get("vision_runs", [])

    if vision_breakdown or vision_props:
        print(f"\n\n  VISION PIPELINE DETAIL (Division 6)")
        print(f"  {'─' * 66}")

        if vision_breakdown:
            print(f"  Processing status:")
            for status, count in sorted(vision_breakdown.items(), key=lambda x: x[1], reverse=True):
                print(f"    {status:<12} {count:>8,}")

        if vision_props:
            print(f"\n  Property coverage (photos seen by The Eye):")
            for prop_name, count in vision_props:
                bar = "#" * min(count // 5, 40)
                print(f"    {prop_name:<40} {count:>5}  {bar}")

        if vision_runs_data:
            print(f"\n  Ingestion runs:")
            for vr in vision_runs_data:
                path_short = os.path.basename(vr["path"])
                print(f"    Run #{vr['run_id']:<2} {path_short:<25} "
                      f"found:{vr['found']:>6,} done:{vr['processed']:>5,} "
                      f"fail:{vr['failed']:>3} [{vr['status']}]")

    # ── THE BLIND SPOT ──
    print(f"\n\n  {'=' * 66}")
    print(f"  THE BLIND SPOT — WHAT THE BRAIN IS IGNORING")
    print(f"  {'=' * 66}")

    blind_images = img_count - img_total
    blind_videos = vid_count

    if blind_images > 0:
        pct = (blind_images / img_count * 100) if img_count > 0 else 0
        print(f"\n  IMAGES:   {blind_images:,} of {img_count:,} ({pct:.1f}%) still unseen.")
        if img_total > 0:
            print(f"            {img_total:,} have been processed. The Eye is open but working.")
        else:
            print(f"            The Brain has NEVER seen a single photo.")
        print(f"")
        print(f"  Unseen images include:")
        print(f"    - Cabin listing photos (interiors, exteriors, amenities)")
        print(f"    - Maintenance evidence (pre/post repair documentation)")
        print(f"    - Property condition records (dated inspections)")
        print(f"    - Marketing assets (hero shots, drone footage stills)")

    if blind_videos > 0:
        print(f"\n  WARNING: {blind_videos:,} videos sit completely unprocessed.")
        print(f"  Includes security footage, property walkthroughs, and archive reels.")

    email_count = grand_totals.get("EMAIL", {}).get("count", 0)
    if email_count > 0:
        print(f"\n  NOTE: {email_count:,} raw email files (.eml/.msg) on NAS. Check if ingested.")

    # ── RECOMMENDED ACTIONS ──
    print(f"\n\n  {'=' * 66}")
    print(f"  RECOMMENDED ACTIONS")
    print(f"  {'=' * 66}")

    actions = []
    if blind_images > 100:
        if img_total > 0:
            actions.append((
                "CONTINUE VISION INGESTION (Division 6 — The Eye is active)",
                f"The Eye has processed {img_total:,} images so far. {blind_images:,} remain.\n"
                f"    Running via: screen -r vision_crawler\n"
                f"    Or restart:  screen -dmS vision_crawler bash src/vision_deep_crawl.sh\n"
                f"    At ~15s/image, remaining ETA: ~{blind_images * 15 / 3600:.0f} hours."
            ))
        else:
            actions.append((
                "DEPLOY 'THE EYE' (Division 6 — Vision Intelligence)",
                f"Deploy LLaVA/Bakllava on Spark 1 to process {blind_images:,} images.\n"
                f"    Each image gets a text description fed into the Legal Cortex.\n"
                f"    The Muscle (Spark 1) already has llama3.2-vision:90b loaded."
            ))

    if blind_videos > 50:
        actions.append((
            "VIDEO FRAME EXTRACTION",
            f"Extract keyframes from {blind_videos:,} videos, then feed to The Eye.\n"
            f"    Priority: property walkthrough videos and security footage."
        ))

    if vector_count > 0 and text_available > 0:
        coverage = min(100, (vector_count / (text_available * 5)) * 100)
        if coverage < 80:
            actions.append((
                "EXPAND TEXT INGESTION",
                f"Estimated text coverage: {coverage:.0f}%. Re-run RAG ingest on uncovered documents."
            ))

    if not actions:
        actions.append(("SYSTEM NOMINAL", "All intelligence layers are operational."))

    for i, (title, desc) in enumerate(actions, 1):
        print(f"\n  {i}. {title}")
        print(f"    {desc}")

    print(f"\n{'=' * 72}")
    print(f"  AUDIT COMPLETE")
    print(f"{'=' * 72}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 72)
    print("  FORTRESS PRIME — FULL SYSTEM AUDIT")
    print("  Quantifying the Delta: What exists vs. what the Brain knows")
    print("=" * 72)
    print()

    start_time = time.time()

    # ── Phase 1: Physical Storage Scan ──
    print("PHASE 1: PHYSICAL STORAGE INVENTORY")
    print("-" * 72)
    scan_results = {}
    for label, path in SCAN_TARGETS.items():
        scan_results[label] = scan_storage(path, label)

    # ── Phase 2: Cognitive Audit ──
    print("\n\nPHASE 2: COGNITIVE LAYER AUDIT")
    print("-" * 72)
    chroma_result = audit_chromadb()

    # ── Phase 3: Financial Vault ──
    print("\n\nPHASE 3: FINANCIAL VAULT AUDIT")
    print("-" * 72)
    postgres_result = audit_postgres()

    # ── Phase 4: Executive Summary ──
    print_executive_summary(scan_results, chroma_result, postgres_result)

    elapsed = time.time() - start_time
    print(f"\n  Total audit time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
