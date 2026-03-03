"""
Fortress Prime — Operation Crown Jewels
Rescues critical business assets from the Master Index to the War Room.
Targets: QuickBooks, CAD, InDesign, and key SQL databases.

Usage: python rescue_crown_jewels.py
"""
import sqlite3
import os
import shutil
import hashlib
import logging
import sys
import time

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
WAR_ROOM = "/mnt/fortress_nas/Enterprise_War_Room/Crown_Jewels"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/rescue_mission.log")

# THE RESCUE LIST (Extension -> Destination Folder)
TARGETS = {
    '.qbw': 'Financial/Active_Company_Files',
    '.qbb': 'Financial/Backups',
    '.qbm': 'Financial/Memorized_Transactions',
    '.dwg': 'Architecture/CAD_Drawings',
    '.dxf': 'Architecture/DXF_Exports',
    '.indd': 'Design/InDesign_Projects',
    '.sql': 'Databases/SQL_Dumps',
}

# Setup Logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)


def rescue():
    print(f"STARTING OPERATION: CROWN JEWELS RESCUE")
    print(f"    Source Index: {DB_FILE}")
    print(f"    Target:      {WAR_ROOM}")
    print(f"    Log:         {LOG_FILE}")
    print()

    if not os.path.exists(DB_FILE):
        print("Index not found. Run build_master_index.py first.")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    total_rescued = 0
    total_skipped = 0
    total_failed = 0
    total_bytes = 0
    start = time.time()

    for ext, folder in TARGETS.items():
        dest_root = os.path.join(WAR_ROOM, folder)
        os.makedirs(dest_root, exist_ok=True)

        c.execute("SELECT path, filename, size FROM files WHERE extension = ? ORDER BY size DESC", (ext,))
        results = c.fetchall()

        if not results:
            print(f"    {ext.upper()}: (none found)")
            continue

        # Special filter for SQL: only grab Drupal, large DBs, or legal code files
        if ext == '.sql':
            filtered = []
            for row in results:
                name_lower = row[1].lower()
                size = row[2] or 0
                if ('drupal' in name_lower or
                    'code' in name_lower or
                    'law' in name_lower or
                    'legal' in name_lower or
                    'ga_code' in name_lower or
                    'fortress' in name_lower or
                    'crog' in name_lower or
                    size > 50 * 1024 * 1024):
                    filtered.append(row)
            results = filtered
            if not results:
                print(f"    {ext.upper()}: (none matched SQL filter)")
                continue

        print(f"    {ext.upper()}: Securing {len(results)} files to {folder}...")

        # Deduplicate by filename (keep largest version)
        seen = {}
        for row in results:
            name = row[1]
            size = row[2] or 0
            if name not in seen or size > seen[name][2]:
                seen[name] = row

        deduped = list(seen.values())
        rescued_this = 0

        for row in deduped:
            src = row[0]
            name = row[1]
            size = row[2] or 0
            dest = os.path.join(dest_root, name)

            if not os.path.exists(src):
                total_failed += 1
                logging.warning(f"SOURCE MISSING: {src}")
                sys.stdout.write("x")
                continue

            if os.path.exists(dest):
                total_skipped += 1
                sys.stdout.write("s")
                continue

            try:
                shutil.copy2(src, dest)
                # Size verification
                dest_size = os.path.getsize(dest)
                if dest_size == os.path.getsize(src):
                    total_rescued += 1
                    total_bytes += dest_size
                    rescued_this += 1
                    logging.info(f"SECURED: {name} ({dest_size:,} bytes) from {os.path.dirname(src)}")
                    sys.stdout.write(".")
                else:
                    total_failed += 1
                    logging.error(f"SIZE MISMATCH: {name}")
                    os.remove(dest)
                    sys.stdout.write("!")
            except Exception as e:
                total_failed += 1
                logging.error(f"FAIL: {src} - {e}")
                sys.stdout.write("!")

            sys.stdout.flush()

        if rescued_this > 0:
            print(f" ({rescued_this} secured)")
        else:
            print(f" (all already secured)")

    elapsed = int(time.time() - start)
    mb = total_bytes / (1024 * 1024)

    print()
    print("=" * 50)
    print(f"MISSION COMPLETE")
    print(f"    Rescued:  {total_rescued} files ({mb:.1f} MB)")
    print(f"    Skipped:  {total_skipped} (already in War Room)")
    print(f"    Failed:   {total_failed}")
    print(f"    Time:     {elapsed} seconds")
    print(f"    Location: {WAR_ROOM}")
    print(f"    Log:      {LOG_FILE}")
    print("=" * 50)

    conn.close()


if __name__ == "__main__":
    rescue()
