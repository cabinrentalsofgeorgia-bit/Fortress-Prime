"""
Fortress Prime — Coverage Auditor
Queries the Master Index to generate a census report showing
exactly which shares were indexed and how many files from each.
Does NOT re-scan the drive — reads from the existing 719K-record database.

Usage: python audit_coverage.py
"""
import sqlite3
import os

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
MOUNT_ROOT = "/mnt/vol1_source"


def audit():
    if not os.path.exists(DB_FILE):
        print("No Index Found. Run build_master_index.py first.")
        return

    print(f"GENERATING COVERAGE REPORT FROM INDEX")
    print(f"    Database: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Get total count first
    c.execute("SELECT COUNT(*) FROM files")
    total_expected = c.fetchone()[0]
    print(f"    Records in index: {total_expected:,}")

    print("    ...Querying all records...")
    c.execute("SELECT path, size FROM files")

    shares = {}
    total_files = 0
    total_size = 0

    for path, size in c.fetchall():
        total_files += 1
        total_size += (size or 0)

        # Parse the path to find the Share Name
        # Format: /mnt/vol1_source/Category/ShareName/...
        if path.startswith(MOUNT_ROOT):
            parts = path.replace(MOUNT_ROOT, "").strip("/").split("/")
            if len(parts) >= 2:
                share_key = f"{parts[0]}/{parts[1]}"
            elif len(parts) == 1:
                share_key = f"{parts[0]}/[root]"
            else:
                share_key = "Root/Misc"
        else:
            share_key = "Unknown_Mount"

        if share_key not in shares:
            shares[share_key] = {"count": 0, "size": 0}

        shares[share_key]["count"] += 1
        shares[share_key]["size"] += (size or 0)

    conn.close()

    # --- PRINT REPORT ---
    print()
    print("=" * 75)
    print(f"  FULL SYSTEM CENSUS ({total_files:,} files verified)")
    print("=" * 75)
    print(f"  {'SHARE NAME':<40} | {'FILES':>10} | {'SIZE (GB)':>10}")
    print("  " + "-" * 70)

    for share in sorted(shares.keys()):
        stats = shares[share]
        gb = stats['size'] / (1024 ** 3)
        print(f"  {share:<40} | {stats['count']:>10,} | {gb:>10.2f}")

    print("  " + "-" * 70)
    print(f"  {'TOTAL':<40} | {total_files:>10,} | {(total_size / (1024**3)):>10.2f}")
    print("=" * 75)

    # --- COVERAGE CHECK ---
    print()
    expected_shares = [
        "Business/CROG",
        "Business/CROG_Workspace",
        "Business/Legal",
        "Business/MarketClub",
        "Personal/Documents",
        "Personal/Photos",
        "Personal/Video_Library",
        "System/Homes",
        "System/Public",
        "System/Security_Check",
    ]

    print("  SHARE COVERAGE CHECK:")
    all_found = True
    for s in expected_shares:
        if s in shares:
            count = shares[s]["count"]
            status = "OK" if count > 0 else "EMPTY"
            print(f"    [{status:>5}] {s} ({count:,} files)")
        else:
            print(f"    [MISS!] {s} (NOT IN INDEX)")
            all_found = False

    # Check for unexpected shares
    known = set(expected_shares)
    extras = [s for s in shares if s not in known]
    if extras:
        print(f"\n  ADDITIONAL SHARES FOUND:")
        for s in sorted(extras):
            print(f"    [EXTRA] {s} ({shares[s]['count']:,} files)")

    print()
    if all_found:
        print("  ALL EXPECTED SHARES PRESENT IN INDEX.")
    else:
        print("  WARNING: Some shares are MISSING from the index!")


if __name__ == "__main__":
    audit()
