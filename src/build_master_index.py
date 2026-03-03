"""
Fortress Prime — Enterprise Live Indexer
Walks the entire Volume 1 source mount and builds a SQLite index
of every file for sub-second forensic search.

Uses batched transactions for speed (20K inserts per commit).
Designed for 570K+ files without crashing.

Usage:
    Direct:     python build_master_index.py
    Background: nohup python build_master_index.py > indexing.log 2>&1 &
    Query:      python build_master_index.py --search "Toccoa"
"""
import os
import sqlite3
import time
import sys

# --- CONFIG ---
SOURCE_ROOT = "/mnt/vol1_source"
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")

# Exclude system noise, but keep EVERYTHING else
SKIP_DIRS = {'node_modules', '.git', 'C-Panel-FullBackup', 'MailPlus',
             '@eaDir', '.Recycle', '.DS_Store', '@SynoResource', '@SynoEAStream',
             '__pycache__', '.Trash'}


def build_index():
    print(f"INITIATING ENTERPRISE FORENSIC INDEX")
    print(f"    Source:   {SOURCE_ROOT}")
    print(f"    Database: {DB_FILE}")

    # Reset Database
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("    (Previous index removed)")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Enable WAL mode for better write performance
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")

    # Create Optimized Schema
    c.execute('''CREATE TABLE files
                 (id INTEGER PRIMARY KEY,
                  path TEXT,
                  filename TEXT,
                  extension TEXT,
                  size INTEGER,
                  mtime REAL)''')

    count = 0
    errors = 0
    start_time = time.time()
    batch_data = []

    print("Crawling file system (Live)...")

    for root, dirs, files in os.walk(SOURCE_ROOT):
        # Prune excluded folders in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]

        for name in files:
            if name.startswith('.'):
                continue

            filepath = os.path.join(root, name)
            try:
                stat = os.stat(filepath)
                size = stat.st_size
                mtime = stat.st_mtime
                _, ext = os.path.splitext(name)

                batch_data.append((filepath, name, ext.lower(), size, mtime))
                count += 1

                # Commit in chunks of 20,000 for speed
                if len(batch_data) >= 20000:
                    c.executemany(
                        'INSERT INTO files (path, filename, extension, size, mtime) VALUES (?,?,?,?,?)',
                        batch_data
                    )
                    conn.commit()
                    batch_data = []
                    elapsed = int(time.time() - start_time)
                    rate = count / max(elapsed, 1)
                    print(f"    Indexed {count:,} items... ({elapsed}s, {rate:.0f}/s) [{os.path.basename(root)}]")

            except Exception:
                errors += 1

    # Final Commit
    if batch_data:
        c.executemany(
            'INSERT INTO files (path, filename, extension, size, mtime) VALUES (?,?,?,?,?)',
            batch_data
        )
        conn.commit()

    # Build indexes AFTER all inserts (faster than maintaining during inserts)
    print("    Building search indexes...")
    c.execute('CREATE INDEX idx_path ON files (path)')
    c.execute('CREATE INDEX idx_filename ON files (filename)')
    c.execute('CREATE INDEX idx_ext ON files (extension)')
    c.execute('CREATE INDEX idx_size ON files (size)')
    conn.commit()

    conn.close()

    duration = int(time.time() - start_time)
    db_size = os.path.getsize(DB_FILE) / (1024 * 1024)
    print("-" * 50)
    print(f"FORENSIC INDEX COMPLETE")
    print(f"    Total Files:  {count:,}")
    print(f"    Errors:       {errors:,}")
    print(f"    Time Taken:   {duration} seconds")
    print(f"    Database:     {DB_FILE} ({db_size:.1f} MB)")


def search_index(keyword):
    """Quick search mode for the master index."""
    if not os.path.exists(DB_FILE):
        print(f"Index not found at {DB_FILE}. Run build first.")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    print(f"\nSearching master index for: \"{keyword}\"")

    # Search by filename
    c.execute(
        "SELECT path, filename, size FROM files WHERE filename LIKE ? ORDER BY size DESC LIMIT 25",
        (f'%{keyword}%',)
    )
    results = c.fetchall()

    if results:
        print(f"\n  {len(results)} hits (by filename, top 25):")
        for path, fname, size in results:
            sz = f"{size:,}" if size else "0"
            print(f"    {sz:>12} bytes  {fname}")
            print(f"                     {os.path.dirname(path)}")
    else:
        print("  No filename matches.")

    # Also search by path
    c.execute(
        "SELECT COUNT(*) FROM files WHERE path LIKE ?",
        (f'%{keyword}%',)
    )
    total = c.fetchone()[0]
    print(f"\n  Total path matches: {total:,}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--search':
        keyword = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if keyword:
            search_index(keyword)
        else:
            print("Usage: python build_master_index.py --search <keyword>")
    else:
        build_index()
