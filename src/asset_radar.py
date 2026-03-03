"""
Fortress Prime — Asset Radar
Scans the Master Index (719K files) for specific professional file types.
Reports what exists and where — does NOT move anything.

Usage: python asset_radar.py
"""
import sqlite3
import os

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")

# THE HUNT LIST
ASSET_CLASSES = {
    "FINANCIAL":    ['.qbw', '.qbb', '.qbm', '.tax', '.ofx', '.qbo'],
    "DESIGN":       ['.indd', '.ai', '.psd', '.eps', '.svg'],
    "CAD_ARCH":     ['.dwg', '.dxf', '.skp', '.pla', '.pln', '.vwx'],
    "DATABASE":     ['.fmp12', '.fp7', '.sqlite', '.db', '.sql', '.mdb', '.accdb'],
    "SPREADSHEET":  ['.xlsx', '.xls', '.csv', '.numbers', '.ods'],
    "PRESENTATION": ['.pptx', '.ppt', '.key', '.keynote'],
    "VIDEO_PRO":    ['.mov', '.mp4', '.avi', '.dv', '.m4v', '.wmv', '.mkv'],
    "ARCHIVE":      ['.zip', '.tar', '.gz', '.rar', '.7z', '.dmg', '.iso'],
}


def scan_assets():
    if not os.path.exists(DB_FILE):
        print("Index not found. Run build_master_index.py first.")
        return

    print(f"ASSET RADAR: SCANNING 719K FILES FOR PROFESSIONAL ASSETS")
    print(f"    Database: {DB_FILE}\n")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    total_found = 0
    category_summary = []

    for category, extensions in ASSET_CLASSES.items():
        # Build query
        placeholders = ','.join(['?'] * len(extensions))
        query = f"SELECT path, filename, size FROM files WHERE extension IN ({placeholders}) ORDER BY size DESC"
        ext_params = [x.lower() for x in extensions]

        c.execute(query, ext_params)
        results = c.fetchall()

        if not results:
            print(f"  {category} {extensions}")
            print(f"    (None found)\n")
            continue

        total_size = sum(r[2] or 0 for r in results)
        size_gb = total_size / (1024 ** 3)
        size_label = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{total_size / (1024**2):.1f} MB"

        print(f"  {category}: {len(results):,} files ({size_label})")

        # Extension breakdown
        ext_counts = {}
        for row in results:
            _, ext = os.path.splitext(row[1])
            ext = ext.lower()
            if ext not in ext_counts:
                ext_counts[ext] = {"count": 0, "size": 0}
            ext_counts[ext]["count"] += 1
            ext_counts[ext]["size"] += (row[2] or 0)

        for ext in sorted(ext_counts.keys()):
            ec = ext_counts[ext]
            esz = ec["size"] / (1024 ** 2)
            print(f"    {ext:<10} {ec['count']:>6,} files  ({esz:>8.1f} MB)")

        # Top locations (share-level breakdown)
        location_counts = {}
        for row in results:
            path = row[0]
            parts = path.split("/")
            # Get /mnt/vol1_source/Category/Share level
            if len(parts) >= 5:
                folder = "/".join(parts[:5])
            else:
                folder = os.path.dirname(path)
            location_counts[folder] = location_counts.get(folder, 0) + 1

        sorted_locs = sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"    Top locations:")
        for loc, count in sorted_locs:
            short = loc.replace("/mnt/vol1_source/", "")
            print(f"      [{count:>5,}] {short}/")

        # Show top 5 largest individual files
        print(f"    Largest files:")
        for row in results[:5]:
            fsize = (row[2] or 0)
            if fsize > 1024 * 1024:
                sz_str = f"{fsize / (1024*1024):.1f} MB"
            elif fsize > 1024:
                sz_str = f"{fsize / 1024:.1f} KB"
            else:
                sz_str = f"{fsize} B"
            # Shorten path
            short_path = row[0].replace("/mnt/vol1_source/", "")
            print(f"      {sz_str:>10}  {short_path}")

        print()
        total_found += len(results)
        category_summary.append((category, len(results), total_size))

    # Final summary
    print("=" * 70)
    print(f"  ASSET RADAR SUMMARY")
    print("=" * 70)
    print(f"  {'CATEGORY':<20} | {'FILES':>10} | {'SIZE':>12}")
    print("  " + "-" * 50)
    grand_size = 0
    for cat, cnt, sz in category_summary:
        grand_size += sz
        sz_label = f"{sz/(1024**3):.2f} GB" if sz > 1024**3 else f"{sz/(1024**2):.1f} MB"
        print(f"  {cat:<20} | {cnt:>10,} | {sz_label:>12}")
    print("  " + "-" * 50)
    print(f"  {'TOTAL':<20} | {total_found:>10,} | {grand_size/(1024**3):.2f} GB")
    print("=" * 70)

    conn.close()


if __name__ == "__main__":
    scan_assets()
