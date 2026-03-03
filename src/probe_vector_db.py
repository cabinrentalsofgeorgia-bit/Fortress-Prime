"""
Fortress Prime - Vector DB Probe
Bypasses ChromaDB library version issues by reading the SQLite directly.
Works regardless of which ChromaDB version created the database.
"""
import sqlite3
import os
import json
from collections import Counter

DB_PATH = "/mnt/fortress_nas/chroma_db/chroma.sqlite3"

def probe():
    print(f"🧠 CONNECTING TO ANCIENT BRAIN: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("❌ Database path not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Collections
    print("\n📚 COLLECTIONS:")
    cur.execute("SELECT id, name, dimension FROM collections")
    collections = cur.fetchall()
    for c in collections:
        print(f"    id={c[0]}  name='{c[1]}'  dimension={c[2]}")

    # 2. Total vector count
    cur.execute("SELECT COUNT(*) FROM embeddings")
    total = cur.fetchone()[0]
    print(f"\n📊 TOTAL VECTORS (memories): {total:,}")

    # 3. Random 5 records - check path format
    print("\n🎲 RANDOM MEMORY CHECK (5 samples — checking source path format):")
    cur.execute("""
        SELECT e.id, em_src.string_value as source, em_pg.string_value as page_label
        FROM embeddings e
        LEFT JOIN embedding_metadata em_src ON e.id = em_src.id AND em_src.key = 'source'
        LEFT JOIN embedding_metadata em_pg  ON e.id = em_pg.id  AND em_pg.key = 'page_label'
        ORDER BY RANDOM()
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"    [{row[0]}] page={row[2]}  source={row[1]}")

    # 4. Toccoa search — metadata source path
    print("\n🕵️  METADATA SCAN: 'Toccoa' in source paths...")
    cur.execute("""
        SELECT DISTINCT string_value FROM embedding_metadata
        WHERE key = 'source' AND string_value LIKE '%Toccoa%'
        LIMIT 20
    """)
    toccoa_sources = cur.fetchall()
    if toccoa_sources:
        print(f"    Found {len(toccoa_sources)} unique source files with 'Toccoa' in path:")
        for s in toccoa_sources:
            print(f"    📄 {s[0]}")
    else:
        print("    (No source paths contain 'Toccoa')")

    # 5. Toccoa search — document text
    print("\n🕵️  DOCUMENT TEXT SCAN: 'Toccoa' in chunk text (first 5)...")
    cur.execute("""
        SELECT e.id, em_src.string_value, em_doc.string_value
        FROM embedding_metadata em_doc
        JOIN embeddings e ON e.id = em_doc.id
        LEFT JOIN embedding_metadata em_src ON e.id = em_src.id AND em_src.key = 'source'
        WHERE em_doc.key = 'chroma:document' AND em_doc.string_value LIKE '%Toccoa%'
        LIMIT 5
    """)
    text_hits = cur.fetchall()
    if text_hits:
        print(f"    Found chunks with 'Toccoa' in text:")
        for row in text_hits:
            snippet = row[2][:180].replace('\n', ' ') if row[2] else ''
            print(f"    📄 Source: {row[1]}")
            print(f"       Preview: {snippet}...")
            print()
    else:
        print("    (No text chunks contain 'Toccoa')")

    # 6. Count Toccoa text hits total
    cur.execute("""
        SELECT COUNT(*) FROM embedding_metadata
        WHERE key = 'chroma:document' AND string_value LIKE '%Toccoa%'
    """)
    toccoa_total = cur.fetchone()[0]
    print(f"    TOTAL 'Toccoa' text chunks: {toccoa_total}")

    # 7. Unique source files — path prefix analysis (Translation Layer check)
    print("\n📊 SOURCE PATH PREFIXES (Top 10 — shows where files 'were' when indexed):")
    cur.execute("""
        SELECT string_value FROM embedding_metadata
        WHERE key = 'source'
        LIMIT 2000
    """)
    paths = [row[0] for row in cur.fetchall() if row[0]]
    prefix_counter = Counter()
    for p in paths:
        # Extract first 3 path components as prefix
        parts = p.split('/')
        prefix = '/'.join(parts[:4]) if len(parts) >= 4 else p
        prefix_counter[prefix] += 1

    for prefix, cnt in prefix_counter.most_common(10):
        print(f"    {cnt:5d} chunks  {prefix}/...")

    # 8. Total unique source files
    cur.execute("SELECT COUNT(DISTINCT string_value) FROM embedding_metadata WHERE key = 'source'")
    unique_sources = cur.fetchone()[0]
    print(f"\n📁 TOTAL UNIQUE SOURCE FILES: {unique_sources:,}")

    conn.close()
    print("\n✅ PROBE COMPLETE")

if __name__ == "__main__":
    probe()
