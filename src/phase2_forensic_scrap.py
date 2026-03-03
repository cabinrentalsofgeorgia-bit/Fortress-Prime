import argparse
import logging
import os
import shutil
import sqlite3
from typing import Dict, List

DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
WAR_ROOM_ROOT = "/mnt/fortress_nas/Enterprise_War_Room"
MAX_COPY_SIZE_BYTES = 500 * 1024 * 1024
SOURCE_PREFIX = "/mnt/vol1_source/"

PROFILE_TARGETS: Dict[str, Dict[str, List[str]]] = {
    "strict": {
        "AI_Projects": ["ipynb", "requirements.txt", "huggingface"],
        "Legal_Evidence": ["deposition", "plaintiff", "defendant", "court", "exhibit"],
        "Financial_Records": ["tax", "1099", "k-1", "ledger", "invoice"],
        "Property_Records": ["deed", "plat", "survey", "warranty", "easement"],
        "Web_Assets": ["drupal", "public_html", "wp-content", "cpanel"],
        "The_Law": ["ocga", "statute", "title 44", "georgia code"],
    },
    "uncapped": {
        "Legal_Evidence": ["deposition", "plaintiff", "defendant", "court", "exhibit", "louchery", "orr matter"],
        "Financial_Records": ["tax", "1099", "k-1", "ledger", "invoice", "quickbooks", "qbw", "qbb"],
        "Property_Records": ["deed", "plat", "survey", "warranty", "easement", "toccoa", "amber ridge", "morgan st"],
        "The_Law_Deep_Search": ["ocga", "statute", "georgia code", "title 44", "law library"],
    },
    "infinity": {
        "Financial_Records": ["tax", "1099", "k-1", "ledger", "invoice", "quickbooks", "qbw", "qbb", "receipt", "financial"],
    },
}


def build_sql(keywords: List[str], include_path: bool, limit: int | None) -> tuple[str, List[str]]:
    query_parts: List[str] = []
    params: List[str] = []
    for keyword in keywords:
        if include_path:
            query_parts.append("filename LIKE ? OR path LIKE ?")
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")
        else:
            query_parts.append("filename LIKE ?")
            params.append(f"%{keyword}%")

    limit_clause = f" LIMIT {limit}" if limit is not None else ""
    sql = f"SELECT path, size FROM files WHERE {' OR '.join(query_parts)}{limit_clause}"
    return sql, params


def run_scrap(profile: str, limit: int | None, include_path: bool, log_file: str) -> None:
    logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(message)s")
    targets = PROFILE_TARGETS[profile]
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    total_moved = 0

    print(f"Starting forensic scrap profile={profile} include_path={include_path} limit={limit}")
    for category, keywords in targets.items():
        dest_root = os.path.join(WAR_ROOM_ROOT, category)
        print(f"\nTarget: {category}")
        sql, params = build_sql(keywords, include_path=include_path, limit=limit)
        cursor.execute(sql, params)
        results = cursor.fetchall()

        if not results:
            print("  No matches found.")
            continue

        print(f"  Found {len(results):,} candidates.")
        moved_for_category = 0
        for src, size in results:
            if size > MAX_COPY_SIZE_BYTES:
                continue
            rel_path = src.replace(SOURCE_PREFIX, "")
            dest = os.path.join(dest_root, rel_path)
            try:
                if not os.path.exists(dest):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
                    moved_for_category += 1
                    total_moved += 1
            except Exception as exc:  # noqa: BLE001
                logging.error("Copy failed: %s - %s", src, exc)

        print(f"  Secured {moved_for_category:,} new items.")

    conn.close()
    print(f"\nScrap complete. Secured {total_moved:,} files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canonical forensic scrap runner.")
    parser.add_argument("--profile", choices=["strict", "uncapped", "infinity"], default="strict")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Result cap. Use 0 for no limit.",
    )
    parser.add_argument("--include-path", action="store_true", help="Match against both filename and full path.")
    parser.add_argument(
        "--log-file",
        default=os.path.expanduser("~/Fortress-Prime/forensic_scrap.log"),
        help="Path to log file.",
    )
    args = parser.parse_args()

    resolved_limit = None if args.limit == 0 else args.limit
    if args.profile == "strict" and args.include_path is False:
        include_path = False
    else:
        include_path = True if args.profile in {"uncapped", "infinity"} else args.include_path

    run_scrap(profile=args.profile, limit=resolved_limit, include_path=include_path, log_file=args.log_file)
