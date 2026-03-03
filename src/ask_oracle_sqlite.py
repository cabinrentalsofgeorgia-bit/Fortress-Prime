"""
Fortress Prime — The Iron-Clad Oracle (SQLite Edition)
No chromadb dependency. Pure sqlite3.
Searches 224K vectors by filename/path AND document text content.
Translates dead /mnt/warehouse/ paths to live /mnt/vol1_source/ mounts.
Recovers files to the War Room.

Usage:
    Interactive:   python ask_oracle_sqlite.py
    Single query:  python ask_oracle_sqlite.py "Toccoa Survey"
"""
import sqlite3
import os
import shutil
import sys

# --- CONFIG ---
DB_PATH = "/mnt/fortress_nas/chroma_db/chroma.sqlite3"
WAR_ROOM = "/mnt/fortress_nas/Enterprise_War_Room/Oracle_Recoveries"

# THE TRANSLATION MAP (Calibrated from verification)
# "Dead Path" (DB) -> "Live Path" (Volume 1)
PATH_MAP = {
    "/mnt/warehouse/legal":         "/mnt/vol1_source/Business/Legal",
    "/mnt/warehouse/crog_business": "/mnt/vol1_source/Business/CROG",
    "/mnt/warehouse/documents":     "/mnt/vol1_source/Personal/Documents",
    "/mnt/warehouse/photos":        "/mnt/vol1_source/Personal/Photos",
    "/mnt/warehouse/Storage":       "/mnt/vol1_source/Storage",
}


def translate_path(db_path):
    """Map old /mnt/warehouse/ paths to current /mnt/vol1_source/ locations."""
    if not db_path:
        return None
    for dead, live in PATH_MAP.items():
        if db_path.startswith(dead):
            return db_path.replace(dead, live, 1)
    # Fallback: generic root swap
    return db_path.replace("/mnt/warehouse", "/mnt/vol1_source", 1)


def run_search(conn, query_term):
    """Search the Oracle for a single query term."""
    c = conn.cursor()

    print(f"\n{'='*60}")
    print(f"   QUERY: \"{query_term}\"")
    print(f"   ...Scanning 224,000 records...")
    print(f"{'='*60}\n")

    # --- SEARCH 1: File paths containing the keyword ---
    c.execute("""
        SELECT DISTINCT string_value
        FROM embedding_metadata
        WHERE key = 'source' AND string_value LIKE ?
        LIMIT 30
    """, (f'%{query_term}%',))
    path_hits = [row[0] for row in c.fetchall()]

    # --- SEARCH 2: Document text containing the keyword ---
    # (finds files whose CONTENT mentions the keyword, even if the filename doesn't)
    c.execute("""
        SELECT DISTINCT em_src.string_value
        FROM embedding_metadata em_doc
        JOIN embeddings e ON e.id = em_doc.id
        JOIN embedding_metadata em_src ON e.id = em_src.id AND em_src.key = 'source'
        WHERE em_doc.key = 'chroma:document'
          AND em_doc.string_value LIKE ?
        LIMIT 50
    """, (f'%{query_term}%',))
    text_hits = [row[0] for row in c.fetchall()]

    # Merge and deduplicate, path hits first (higher confidence)
    seen = set()
    all_sources = []
    for src in path_hits + text_hits:
        if src and src not in seen:
            seen.add(src)
            all_sources.append(src)

    if not all_sources:
        print("   No hits found. Try different keywords.")
        return

    # Deduplicate by basename (same file from different old copies)
    deduped = []
    seen_basenames = set()
    for src in all_sources:
        bn = os.path.basename(src).lower()
        if bn not in seen_basenames:
            seen_basenames.add(bn)
            deduped.append(src)

    found_files = []
    ghost_files = []

    in_path = len(path_hits)
    in_text = len(text_hits)
    print(f"   Hits: {in_path} by filename | {in_text} by content | {len(deduped)} unique files\n")

    for i, dead_path in enumerate(deduped[:20]):
        live_path = translate_path(dead_path)
        basename = os.path.basename(live_path)

        if os.path.exists(live_path):
            status = "\033[92m ALIVE\033[0m"
            found_files.append(live_path)
        else:
            status = "\033[91m GHOST\033[0m"
            ghost_files.append(live_path)

        # Show which search found it
        match_type = ""
        if dead_path in path_hits and dead_path in text_hits:
            match_type = "[path+text]"
        elif dead_path in path_hits:
            match_type = "[path]"
        else:
            match_type = "[text]"

        print(f"   [{i+1:2d}] [{status}] {basename}  {match_type}")
        print(f"        {os.path.dirname(live_path)}")

    print(f"\n   SUMMARY: {len(found_files)} ALIVE | {len(ghost_files)} GHOST | {len(deduped)} unique")

    # Recovery option
    if found_files:
        print(f"\n   {len(found_files)} files ready for extraction.")
        try:
            confirm = input("   Copy to War Room? (y/n): ")
        except EOFError:
            confirm = 'n'
            print("   (non-interactive — skipping migration)")

        if confirm.strip().lower() == 'y':
            tag = query_term.replace(" ", "_").replace("/", "-")[:50]
            dest_root = os.path.join(WAR_ROOM, tag)
            os.makedirs(dest_root, exist_ok=True)

            copied = 0
            for src in found_files:
                fname = os.path.basename(src)
                dest = os.path.join(dest_root, fname)
                if os.path.exists(dest):
                    print(f"       (skip) {fname} — already recovered")
                    continue
                try:
                    shutil.copy2(src, dest)
                    sz = os.path.getsize(dest)
                    print(f"       Secured: {fname} ({sz:,} bytes)")
                    copied += 1
                except Exception as e:
                    print(f"       FAILED: {fname} — {e}")

            print(f"\n   {copied} files secured to: {dest_root}")


def main():
    print(f"\n{'='*60}")
    print(f"   THE IRON-CLAD ORACLE (SQLite Edition)")
    print(f"   Brain: {DB_PATH}")
    print(f"   224,209 vectors | 16,883 source files")
    print(f"   Translation: /mnt/warehouse/ -> /mnt/vol1_source/")
    print(f"{'='*60}")

    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)

    # Single-shot mode via command line
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_search(conn, query)
        conn.close()
        return

    # Interactive mode
    while True:
        print()
        try:
            query_term = input("   Enter Search Term (or 'exit'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if query_term.lower() in ('exit', 'quit', ''):
            break

        run_search(conn, query_term)

    conn.close()
    print("\n   Oracle offline.\n")


if __name__ == "__main__":
    main()
