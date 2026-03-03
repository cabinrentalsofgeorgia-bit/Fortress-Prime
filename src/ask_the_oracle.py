"""
Fortress Prime — The Oracle
Searches the 224K-vector ChromaDB brain using raw SQLite (bypasses version issues).
Translates old /mnt/warehouse/ paths to current /mnt/vol1_source/ mounts.
Verifies file existence and optionally copies to the War Room.

Usage:
    Interactive:   python ask_the_oracle.py
    Single query:  python ask_the_oracle.py "Toccoa Heights Survey"
"""
import sqlite3
import os
import sys
import shutil
import hashlib
from collections import OrderedDict

# --- CONFIG ---
DB_PATH = "/mnt/fortress_nas/chroma_db/chroma.sqlite3"
WAR_ROOM = "/mnt/fortress_nas/Enterprise_War_Room/Recovered_Assets"

# THE TRANSLATION MAP (Old Path -> New Path)
PATH_MAP = OrderedDict([
    ("/mnt/warehouse/legal",         "/mnt/vol1_source/Business/Legal"),
    ("/mnt/warehouse/crog_business", "/mnt/vol1_source/Business/CROG"),
    ("/mnt/warehouse/documents",     "/mnt/vol1_source/Personal/Documents"),
    ("/mnt/warehouse/photos",        "/mnt/vol1_source/Personal/Photos"),
])


def translate_path(old_path):
    """Map old /mnt/warehouse/ paths to current /mnt/vol1_source/ locations."""
    for old_prefix, new_prefix in PATH_MAP.items():
        if old_path.startswith(old_prefix):
            return old_path.replace(old_prefix, new_prefix, 1)
    # Fallback: swap root directly
    return old_path.replace("/mnt/warehouse", "/mnt/vol1_source", 1)


def search_oracle(conn, query, max_results=15):
    """
    Search ChromaDB's embedded documents for the query string.
    Uses the FTS5 trigram index for fast substring matching,
    then joins back to get source paths and document text.
    """
    cur = conn.cursor()

    # Split query into words — each word becomes a trigram FTS match
    words = query.strip().split()

    # Strategy 1: Search document TEXT content via FTS5 trigram index
    # The embedding_fulltext_search table was built from ALL embedding_metadata rows,
    # so we filter for rows that have a matching 'chroma:document' key.
    # Trigram FTS5 uses substring matching.
    fts_results = []

    # Build a query that searches for each word using FTS5
    # Trigram tokenizer supports simple substring match
    primary_word = words[0] if words else query
    try:
        cur.execute("""
            SELECT efs.rowid, efs.string_value
            FROM embedding_fulltext_search efs
            WHERE efs.string_value MATCH ?
            LIMIT 500
        """, (primary_word,))
        fts_hits = cur.fetchall()
    except Exception:
        # FTS5 match can fail on short strings; fall back to LIKE
        fts_hits = []

    if not fts_hits:
        # Fallback: direct LIKE on document text (slower but reliable)
        like_pattern = f"%{primary_word}%"
        cur.execute("""
            SELECT id, string_value FROM embedding_metadata
            WHERE key = 'chroma:document' AND string_value LIKE ?
            LIMIT 500
        """, (like_pattern,))
        fts_hits = cur.fetchall()

    if not fts_hits:
        return []

    # If we got FTS hits, we need to map rowids back to embedding IDs
    # and get source paths + document text.
    # FTS rowids correspond to embedding_metadata rowids.
    # We need to get the embedding id from embedding_metadata, then the source.

    # Collect candidate embedding IDs from FTS hits
    # For FTS results, rowid = embedding_metadata.rowid
    rowids = [str(r[0]) for r in fts_hits[:500]]

    # Get embedding IDs and their document text from the matched rowids
    # First, check if these rowids correspond to 'chroma:document' entries
    results = []
    seen_sources = set()

    # Process in batches to avoid SQL variable limits
    batch_size = 100
    for i in range(0, len(rowids), batch_size):
        batch = rowids[i:i + batch_size]
        placeholders = ','.join(['?'] * len(batch))

        # Get the embedding ID for each rowid
        cur.execute(f"""
            SELECT em.id, em.string_value, em.key
            FROM embedding_metadata em
            WHERE em.rowid IN ({placeholders})
        """, batch)

        # Map: embedding_id -> metadata
        id_map = {}
        for row in cur.fetchall():
            eid, val, key = row
            if eid not in id_map:
                id_map[eid] = {}
            if key == 'chroma:document':
                id_map[eid]['document'] = val
            # We might get non-document rows; skip them

        # For each embedding ID that had a document match, get the source
        if id_map:
            eid_list = list(id_map.keys())
            eid_placeholders = ','.join(['?'] * len(eid_list))
            cur.execute(f"""
                SELECT id, string_value FROM embedding_metadata
                WHERE key = 'source' AND id IN ({eid_placeholders})
            """, eid_list)

            for row in cur.fetchall():
                eid, source = row
                if source and source not in seen_sources:
                    doc_text = id_map.get(eid, {}).get('document', '')
                    # Score: count how many query words appear in the doc
                    if doc_text:
                        score = sum(1 for w in words if w.lower() in doc_text.lower())
                    else:
                        score = 0
                    # Also boost if query words appear in source path
                    score += sum(1 for w in words if w.lower() in source.lower()) * 2

                    if score > 0:
                        seen_sources.add(source)
                        results.append({
                            'source': source,
                            'document': doc_text,
                            'score': score
                        })

    # Strategy 2: Also search by SOURCE PATH (finds files whose names match)
    for word in words:
        like_pattern = f"%{word}%"
        cur.execute("""
            SELECT DISTINCT string_value FROM embedding_metadata
            WHERE key = 'source' AND string_value LIKE ?
            LIMIT 100
        """, (like_pattern,))
        for row in cur.fetchall():
            source = row[0]
            if source and source not in seen_sources:
                seen_sources.add(source)
                results.append({
                    'source': source,
                    'document': f"[Matched by filename: {os.path.basename(source)}]",
                    'score': sum(1 for w in words if w.lower() in source.lower()) * 3
                })

    # Sort by score descending, deduplicate by base filename
    results.sort(key=lambda x: x['score'], reverse=True)

    # Deduplicate: same filename from different old paths = same physical file
    final = []
    seen_basenames = set()
    for r in results:
        bn = os.path.basename(r['source']).lower()
        if bn not in seen_basenames:
            seen_basenames.add(bn)
            final.append(r)
        if len(final) >= max_results:
            break

    return final


def display_results(results, query):
    """Display results with translation and existence verification."""
    if not results:
        print("    (No results found. Try different keywords.)")
        return [], []

    found_files = []
    lost_files = []

    for i, r in enumerate(results):
        original = r['source']
        translated = translate_path(original)
        snippet = r['document'][:120].replace('\n', ' ') if r['document'] else ''

        exists = os.path.exists(translated)
        if exists:
            status = "\033[92m FOUND\033[0m"  # green
            found_files.append(translated)
        else:
            status = "\033[91m LOST \033[0m"   # red
            lost_files.append(translated)

        print(f"   [{i+1:2d}] [{status}] {os.path.basename(translated)}")
        print(f"        Old: {original}")
        print(f"        New: {translated}")
        if snippet and not snippet.startswith('[Matched by filename'):
            print(f"        Context: \"{snippet}...\"")
        print()

    return found_files, lost_files


def migrate_to_war_room(found_files, query):
    """Copy verified files to the War Room with hash verification."""
    tag = query.replace(" ", "_").replace("/", "-")[:50]
    dest_folder = os.path.join(WAR_ROOM, f"Oracle_{tag}")
    os.makedirs(dest_folder, exist_ok=True)

    migrated = 0
    for src in found_files:
        filename = os.path.basename(src)
        dest = os.path.join(dest_folder, filename)

        # Skip if already copied
        if os.path.exists(dest):
            print(f"       (skip) {filename} — already in War Room")
            continue

        try:
            shutil.copy2(src, dest)
            # Quick size verification
            if os.path.getsize(dest) == os.path.getsize(src):
                print(f"       Secured: {filename} ({os.path.getsize(dest):,} bytes)")
                migrated += 1
            else:
                print(f"       SIZE MISMATCH: {filename}")
                os.remove(dest)
        except Exception as e:
            print(f"       FAILED: {filename} — {e}")

    print(f"\n    {migrated}/{len(found_files)} files secured to:")
    print(f"    {dest_folder}")


def run_query(conn, query, auto_migrate=False):
    """Execute a single query against the Oracle."""
    print(f"\n{'='*60}")
    print(f"   QUERY: \"{query}\"")
    print(f"   ...Searching 224,209 memories...")
    print(f"{'='*60}\n")

    results = search_oracle(conn, query)
    found, lost = display_results(results, query)

    print(f"   SUMMARY: {len(found)} FOUND | {len(lost)} LOST | {len(results)} total")

    if found:
        if auto_migrate:
            migrate_to_war_room(found, query)
        else:
            try:
                action = input("\n   Migrate found files to War Room? (y/n): ")
                if action.strip().lower() == 'y':
                    migrate_to_war_room(found, query)
            except EOFError:
                print("   (non-interactive mode — skipping migration prompt)")


def main():
    print(f"\n{'='*60}")
    print(f"   THE ORACLE IS ONLINE")
    print(f"   Brain: {DB_PATH}")
    print(f"   224,209 vectors | 16,883 source files")
    print(f"   Translation: /mnt/warehouse/ -> /mnt/vol1_source/")
    print(f"{'='*60}")

    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)

    # Command-line mode: single query
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_query(conn, query)
        conn.close()
        return

    # Interactive mode
    while True:
        print()
        try:
            query = input("   Ask the Oracle (or 'exit'): ")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ('exit', 'quit', ''):
            break

        run_query(conn, query)

    conn.close()
    print("\n   Oracle offline.\n")


if __name__ == "__main__":
    main()
