import sqlite3
import os
import shutil
import logging

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
WAR_ROOM_ROOT = "/mnt/fortress_nas/Enterprise_War_Room"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/extraction_phase2.log")

# MAPPING: Category -> Search Terms for Automatic Extraction
# We find folders that match these names and mirror them to the War Room
EXTRACTION_MAP = {
    "Legal/Higginbotham":        ["Higginbotham"],
    "Legal/Lawsuits":            ["Louchery", "Orr Matter"],
    "Properties/Toccoa_Heights": ["Toccoa Heights"],
    "Properties/200_Amber":      ["200 Amber Ridge"],
    "Financial/Taxes":           ["Tax Return", "Taxes"],
    "Business/CROG_Website":     ["CROG Website", "drupal"],
    "Personal/Gary_Docs":        ["Garys IMAC"],
}

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')


def run_extraction():
    print(f"INITIATING PHASE 2 EXTRACTION (Index: 5.0M+ Files)")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    grand_total = 0

    for category, keywords in EXTRACTION_MAP.items():
        dest_root = os.path.join(WAR_ROOM_ROOT, category)
        print(f"\n  TARGET: {category} (Keywords: {keywords})")

        # 1. Find files matching keywords in path
        params = ['%' + k + '%' for k in keywords]
        where = " OR ".join(["path LIKE ?"] * len(keywords))
        query = f"SELECT DISTINCT path FROM files WHERE {where}"

        c.execute(query, params)
        paths = c.fetchall()

        print(f"   found {len(paths)} matching file paths... filtering...")

        # 2. Smart Copy — preserve original folder structure (Chain of Custody)
        count = 0
        skipped = 0
        failed = 0
        for row in paths:
            src_file = row[0]

            # Skip recycle bins and metadata
            if "#recycle" in src_file or "@eaDir" in src_file:
                continue
            if not os.path.exists(src_file):
                continue

            # Replicate structure in War Room
            rel_path = src_file.replace("/mnt/vol1_source/", "")
            dest_file = os.path.join(dest_root, rel_path)
            dest_dir = os.path.dirname(dest_file)

            try:
                if os.path.exists(dest_file):
                    skipped += 1
                    continue

                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)

                shutil.copy2(src_file, dest_file)
                count += 1

                if count % 100 == 0:
                    print(f"   Moved {count} files...")

            except Exception as e:
                logging.error(f"Failed to copy {src_file}: {e}")
                failed += 1

        print(f"   Secured {count} items | Skipped {skipped} (already exist) | Failed {failed}")
        logging.info(f"{category}: copied={count}, skipped={skipped}, failed={failed}")
        grand_total += count

    conn.close()
    print(f"\nPHASE 2 COMPLETE: {grand_total:,} total files extracted to War Room")
    print(f"   Location: {WAR_ROOM_ROOT}")
    print(f"   Log: {LOG_FILE}")


if __name__ == "__main__":
    run_extraction()
