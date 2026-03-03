import json
import os
import argparse
import datetime
import logging

# --- CONFIG ---
REPORT_FILE = os.path.expanduser("~/Fortress-Prime/nas_audit_report.json")
LOG_FILE = os.path.expanduser("~/Fortress-Prime/cleanup_log.txt")

# Setup Logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

def is_protected(filepath):
    """Returns True if file name contains protected keywords."""
    name = os.path.basename(filepath)
    keywords = ["Final", "Tax", "final", "tax"]
    return any(k in name for k in keywords)

def get_mtime(filepath):
    try:
        return os.path.getmtime(filepath)
    except OSError:
        return 0

def cleanup_duplicates(dry_run=True):
    print(f"🚀 STARTING CLEANUP (Dry Run: {dry_run})")
    print(f"📂 Loading Report: {REPORT_FILE}")
    
    if not os.path.exists(REPORT_FILE):
        print("❌ Report file missing!")
        return

    with open(REPORT_FILE) as f:
        data = json.load(f)

    duplicates = data.get("duplicates", [])
    print(f"🔍 Analyzing {len(duplicates)} duplicate pairs...")
    
    bytes_saved = 0
    files_deleted = 0
    files_skipped = 0

    for entry in duplicates:
        # The report gives us "original" and "duplicate" (the scanner already matched them by hash)
        # But we need to re-evaluate which one to keep based on the PLANNER'S rules.
        
        path_a = entry['original']
        path_b = entry['duplicate']
        
        # Verify both exist before touching anything
        if not os.path.exists(path_a) or not os.path.exists(path_b):
            logging.warning(f"SKIPPING: One file missing pair: {path_a} vs {path_b}")
            files_skipped += 1
            continue

        # --- LOGIC ENGINE ---
        protected_a = is_protected(path_a)
        protected_b = is_protected(path_b)
        
        mtime_a = get_mtime(path_a)
        mtime_b = get_mtime(path_b)

        target_to_delete = None
        reason = ""

        # Rule 4: Both Protected -> Keep Both
        if protected_a and protected_b:
            logging.info(f"CONFLICT: Both files protected. Keeping both.\n  A: {path_a}\n  B: {path_b}")
            files_skipped += 1
            continue
            
        # Rule 2: Keyword Priority
        elif protected_a:
            target_to_delete = path_b
            reason = "Kept protected file (A)"
        elif protected_b:
            target_to_delete = path_a
            reason = "Kept protected file (B)"
            
        # Rule 1: Age Priority (Keep Oldest)
        else:
            if mtime_a < mtime_b:
                target_to_delete = path_b
                reason = "Kept older file (A)"
            elif mtime_b < mtime_a:
                target_to_delete = path_a
                reason = "Kept older file (B)"
            else:
                # Same time? Default to deleting the "duplicate" listed by scanner
                target_to_delete = path_b
                reason = "Timestamps identical. Deleting duplicate."

        # --- EXECUTION ---
        if target_to_delete:
            size = entry.get('size', 0)
            if dry_run:
                logging.info(f"[DRY RUN] Would DELETE: {target_to_delete} ({reason})")
            else:
                try:
                    os.remove(target_to_delete)
                    logging.info(f"DELETED: {target_to_delete} ({reason})")
                    bytes_saved += size
                    files_deleted += 1
                except Exception as e:
                    logging.error(f"FAILED to delete {target_to_delete}: {e}")

    print("-" * 40)
    print(f"✅ OPERATION COMPLETE")
    print(f"   Mode: {'DRY RUN (No changes)' if dry_run else 'LIVE EXECUTION'}")
    print(f"   Files Targeted: {files_deleted}")
    print(f"   Space Reclaimed: {bytes_saved / (1024**2):.2f} MB")
    print(f"   Skipped/Conflict: {files_skipped}")
    print(f"📝 detailed log saved to: {LOG_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Powered NAS Cleanup")
    parser.add_argument("--execute", action="store_true", help="DISABLE dry-run and actually delete files")
    args = parser.parse_args()
    
    cleanup_duplicates(dry_run=not args.execute)
