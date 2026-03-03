import os
import json
import time

# --- CONFIG ---
NAS_ROOT = "/mnt/vol1_source"
OUTPUT_REPORT = os.path.expanduser("~/Fortress-Prime/source_audit_clean.json")
# FOLDERS TO IGNORE (The Noise)
EXCLUDE_DIRS = {"C-Panel-FullBackup", "MailPlus", "Backups", "Recycle", "@eaDir"}

def scan_clean():
    print(f"🔭 STARTING NOISE-FREE AUDIT: {NAS_ROOT}")
    print(f"   Ignoring: {EXCLUDE_DIRS}")
    
    files_registry = {}
    count = 0
    start_time = time.time()

    for root, dirs, files in os.walk(NAS_ROOT):
        # 1. Modify 'dirs' in-place to prevent walking into excluded folders
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        
        for name in files:
            if name.startswith("."): continue # Skip system junk
            
            filepath = os.path.join(root, name)
            size = os.path.getsize(filepath)
            
            # Record it
            files_registry[filepath] = {"size": size}
            
            count += 1
            if count % 1000 == 0:
                print(f"   Scanned {count} files... Last: {name}")

    # Save
    with open(OUTPUT_REPORT, 'w') as f:
        json.dump({"files": files_registry}, f)
    
    print("-" * 40)
    print(f"✅ CLEAN AUDIT COMPLETE")
    print(f"   Files Found (excluding backups): {count:,}")
    print(f"   Report Saved: {OUTPUT_REPORT}")

if __name__ == "__main__":
    scan_clean()
