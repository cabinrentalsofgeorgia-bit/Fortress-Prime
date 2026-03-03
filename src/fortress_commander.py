"""
Fortress Prime — The Fortress Commander v2 (Hybrid Engine)
Combines the Master Index (719K files), Oracle (224K vectors),
and BGE-M3 Cross-Encoder Judge (Spark 1 GPU) into a unified
search-and-recover interface.

Architecture:
    Spark 2 (Manager) — Keyword search via Index + Oracle (broad net)
    Spark 1 (Judge)   — BGE-reranker-v2-m3 cross-encoder (precision filter)

Usage:
    Interactive:   python fortress_commander.py
    Single query:  python fortress_commander.py "Toccoa Heights Deed"
"""
import sqlite3
import os
import shutil
import time
import sys
import requests

# --- CONFIGURATION ---
INDEX_DB = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
ORACLE_DB = "/mnt/fortress_nas/chroma_db/chroma.sqlite3"
WAR_ROOM = "/mnt/fortress_nas/Enterprise_War_Room/Commander_Recoveries"

# Cross-Encoder Judge (Spark 1 GPU — BGE-reranker-v2-m3)
JUDGE_IP = "192.168.0.104"
JUDGE_URL = f"http://{JUDGE_IP}:8000/rerank"
RERANK_ENABLED = True  # Set False to disable cross-encoder reranking

# ORACLE TRANSLATION MAP (Dead -> Live)
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
    return db_path.replace("/mnt/warehouse", "/mnt/vol1_source", 1)


# --- CROSS-ENCODER JUDGE (BGE-reranker-v2-m3 on Spark 1 GPU) ---
def call_judge(query, items, top_k=25):
    """
    Rerank items using the BGE-M3 cross-encoder on Spark 1.
    This is a TRUE cross-encoder — it reads query+document TOGETHER
    and produces a precision relevance score, not cosine similarity.
    """
    if not items:
        return items

    # Build document text for the judge to evaluate
    doc_texts = []
    for item in items:
        path = item.get("path", "")
        basename = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        grandparent = os.path.basename(os.path.dirname(os.path.dirname(path)))
        doc_text = f"{grandparent} / {parent} / {basename}"
        # If we have Oracle document text, include it for deeper judgment
        if item.get("doc_snippet"):
            doc_text += " | Content: " + item["doc_snippet"][:300]
        doc_texts.append(doc_text)

    try:
        # Send to cross-encoder on Spark 1
        payload = {
            "query": query,
            "documents": doc_texts
        }
        resp = requests.post(JUDGE_URL, json=payload, timeout=30)

        if resp.status_code == 200:
            ranked = resp.json().get("ranked", [])
            # Map scores back to items
            # The judge returns documents sorted by score
            score_map = {}
            for r in ranked:
                score_map[r["text"]] = r["score"]

            for i, item in enumerate(items):
                item["rerank_score"] = score_map.get(doc_texts[i], -999)

            items.sort(key=lambda x: x["rerank_score"], reverse=True)
            return items[:top_k]
        else:
            print(f"   Judge error {resp.status_code}: {resp.text[:100]}")
            return items[:top_k]

    except requests.exceptions.ConnectionError:
        print(f"   Judge OFFLINE (Spark 1 not responding). Falling back to keyword ranking.")
        return items[:top_k]
    except Exception as e:
        print(f"   Judge error: {e}. Falling back to keyword ranking.")
        return items[:top_k]


def run_search(conn_idx, conn_orc, query):
    """Execute a unified search across both databases with cross-encoder reranking."""
    c_idx = conn_idx.cursor()
    c_orc = conn_orc.cursor()

    rerank_label = f"BGE-M3 Cross-Encoder @ {JUDGE_IP}" if RERANK_ENABLED else "OFF"
    print(f"\n{'='*70}")
    print(f"   TARGET: \"{query}\"")
    print(f"   Scanning 719K files + 224K vectors | Judge: {rerank_label}")
    print(f"{'='*70}\n")

    hits = {}  # path -> info dict

    # Split multi-word queries into individual terms for broader matching
    terms = [t.strip() for t in query.split() if len(t.strip()) >= 3]
    if not terms:
        terms = [query]

    # 1. SEARCH MASTER INDEX (Filename/path matches — 719K files)
    idx_count = 0
    try:
        # Search for ANY term in filename (OR logic)
        where_clauses = " OR ".join(["filename LIKE ?" for _ in terms])
        params = [f'%{t}%' for t in terms]
        c_idx.execute(
            f"SELECT path, filename, size FROM files WHERE {where_clauses} ORDER BY size DESC LIMIT 200",
            params
        )
        for row in c_idx.fetchall():
            path, fname, size = row
            hits[path] = {"source": "INDEX", "size": size or 0, "path": path, "doc_snippet": ""}
            idx_count += 1
    except Exception as e:
        print(f"   Index Error: {e}")

    # 2. SEARCH ORACLE — source paths (search each term)
    orc_path_count = 0
    try:
        for term in terms:
            c_orc.execute(
                "SELECT DISTINCT string_value FROM embedding_metadata WHERE key='source' AND string_value LIKE ? LIMIT 100",
                (f'%{term}%',)
            )
            for row in c_orc.fetchall():
                live_path = translate_path(row[0])
                if live_path:
                    if live_path in hits:
                        hits[live_path]["source"] += " + ORACLE"
                    else:
                        hits[live_path] = {"source": "ORACLE (path)", "size": 0, "path": live_path, "doc_snippet": ""}
                    orc_path_count += 1
    except Exception as e:
        print(f"   Oracle path error: {e}")

    # 3. SEARCH ORACLE — document text content with snippet extraction
    orc_text_count = 0
    try:
        for term in terms:
            c_orc.execute("""
                SELECT em_src.string_value, SUBSTR(em_doc.string_value, 1, 200)
                FROM embedding_metadata em_doc
                JOIN embeddings e ON e.id = em_doc.id
                JOIN embedding_metadata em_src ON e.id = em_src.id AND em_src.key = 'source'
                WHERE em_doc.key = 'chroma:document'
                  AND em_doc.string_value LIKE ?
                LIMIT 50
            """, (f'%{term}%',))
            for row in c_orc.fetchall():
                live_path = translate_path(row[0])
                snippet = row[1] or ""
                if live_path:
                    if live_path in hits:
                        if "ORACLE" not in hits[live_path]["source"]:
                            hits[live_path]["source"] += " + ORACLE (content)"
                        if len(snippet) > len(hits[live_path].get("doc_snippet", "")):
                            hits[live_path]["doc_snippet"] = snippet
                    else:
                        hits[live_path] = {"source": "ORACLE (content)", "size": 0, "path": live_path, "doc_snippet": snippet}
                    orc_text_count += 1
    except Exception as e:
        print(f"   Oracle text error: {e}")

    print(f"   Hits: {idx_count} by filename | {orc_path_count} by vector path | {orc_text_count} by content")

    # 4. VERIFY — check which files actually exist on disk
    alive = []
    ghost = []
    for path, info in hits.items():
        if os.path.exists(path):
            if info["size"] == 0:
                try:
                    info["size"] = os.path.getsize(path)
                except:
                    pass
            alive.append(info)
        else:
            ghost.append(info)

    # Deduplicate by basename
    seen_basenames = set()
    deduped = []
    for item in sorted(alive, key=lambda x: x["size"], reverse=True):
        bn = os.path.basename(item["path"]).lower()
        if bn not in seen_basenames:
            seen_basenames.add(bn)
            deduped.append(item)

    if not deduped:
        print("   TARGET NOT FOUND.\n")
        return

    # 5. CROSS-ENCODER JUDGE (if enabled)
    if RERANK_ENABLED and len(deduped) > 1:
        print(f"   Cross-Encoder Judge: scoring {len(deduped)} candidates on Spark 1 GPU...")
        deduped = call_judge(query, deduped, top_k=25)

    # 6. REPORT
    total_size = sum(x["size"] for x in deduped)
    size_label = f"{total_size / (1024*1024):.1f} MB" if total_size > 1024*1024 else f"{total_size / 1024:.1f} KB"

    print(f"\n   CONFIRMED ASSETS: {len(deduped)} files ({size_label})")
    if ghost:
        print(f"   Ghost files: {len(ghost)} (in memory but not on disk)")
    print()

    for i, item in enumerate(deduped[:25]):
        basename = os.path.basename(item["path"])
        dirname = os.path.dirname(item["path"])
        sz = item["size"]
        sz_str = f"{sz:,}" if sz < 1024*1024 else f"{sz/(1024*1024):.1f}M"

        score_str = ""
        if "rerank_score" in item:
            score_str = f"  [relevance: {item['rerank_score']:.3f}]"

        print(f"   [{i+1:2d}] {basename}  ({sz_str}){score_str}")
        print(f"        {dirname}")
        print(f"        via: {item['source']}")

    if len(deduped) > 25:
        print(f"\n        ...and {len(deduped) - 25} more.")

    # 7. RECOVERY
    print(f"\n   {len(deduped)} files ready for extraction ({size_label}).")
    try:
        action = input("   EXTRACT ALL? (y/n): ")
    except EOFError:
        action = 'n'
        print("   (non-interactive — skipping extraction)")

    if action.strip().lower() == 'y':
        tag = query.replace(" ", "_").replace("/", "-")[:50]
        batch_folder = os.path.join(WAR_ROOM, tag)
        os.makedirs(batch_folder, exist_ok=True)

        print(f"   Securing assets to: {batch_folder}")
        success = 0
        skipped = 0
        failed = 0

        for item in deduped:
            src = item["path"]
            fname = os.path.basename(src)
            dest = os.path.join(batch_folder, fname)

            if os.path.exists(dest):
                skipped += 1
                continue

            try:
                shutil.copy2(src, dest)
                if os.path.getsize(dest) == os.path.getsize(src):
                    success += 1
                else:
                    failed += 1
                    os.remove(dest)
            except Exception:
                failed += 1

            total_done = success + skipped + failed
            if total_done % 10 == 0:
                sys.stdout.write(f"\r   Progress: {total_done}/{len(deduped)}")
                sys.stdout.flush()

        print(f"\r   EXTRACTION COMPLETE                    ")
        print(f"   Secured: {success} | Skipped: {skipped} | Failed: {failed}")
        print(f"   Location: {batch_folder}")


def main():
    print(f"\n{'='*70}")
    print(f"   FORTRESS COMMANDER v2 (HYBRID ENGINE)")
    print(f"   Master Index : {os.path.basename(INDEX_DB)} (719K files)")
    print(f"   Oracle Brain : {os.path.basename(ORACLE_DB)} (224K vectors)")
    print(f"   Judge        : BGE-reranker-v2-m3 @ Spark 1 ({JUDGE_IP})")
    print(f"   War Room     : {WAR_ROOM}")
    print(f"{'='*70}")

    for db in [INDEX_DB, ORACLE_DB]:
        if not os.path.exists(db):
            print(f"   MISSING: {db}")
            return

    conn_idx = sqlite3.connect(INDEX_DB)
    conn_orc = sqlite3.connect(ORACLE_DB)

    # Single-shot mode
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_search(conn_idx, conn_orc, query)
        conn_idx.close()
        conn_orc.close()
        return

    # Interactive mode
    while True:
        print()
        try:
            query = input("   COMMANDER SEARCH > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if query.lower() in ('exit', 'quit', ''):
            break

        run_search(conn_idx, conn_orc, query)

    conn_idx.close()
    conn_orc.close()
    print("\n   Commander offline.\n")


if __name__ == "__main__":
    main()
