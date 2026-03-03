import os
import shutil
import hashlib
import time
import logging

# --- CONFIG ---
SOURCE_ROOT = "/mnt/vol1_source"
DEST_ROOT = "/mnt/fortress_nas/Property_War_Room"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/migration_projects.log")

# 🎯 THE HUNT LIST
# Any file or folder containing these words will be captured ENTIRELY.
KEYWORDS = [
    "Toccoa", "Heights",       # The Specific Property
    "Deed", "Title", "Plat",   # Ownership Docs
    "Survey", "Warranty",      # Land Docs
    "Court", "Lawsuit", "v.",  # Legal Cases
    "Deposition", "Brief"      # Legal Details
]

# Setup Logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

def get_hash(filepath):
    sha = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(1024 * 1024)
            if not data: break
            sha.update(data)
    return sha.hexdigest()

def matches_keyword(path):
    # Check if any keyword is in the filename or parent folder name
    name = os.path.basename(path).lower()
    parent = os.path.basename(os.path.dirname(path)).lower()
    
    for k in KEYWORDS:
        key = k.lower()
        if key in name or key in parent:
            return True
    return False

def migrate_projects():
    print(f"⚖️  STARTING LEGAL & PROPERTY DRAGNET")
    print(f"    Scanning: {SOURCE_ROOT}")
    print(f"    Targeting Keywords: {KEYWORDS}")
    print(f"    Destination: {DEST_ROOT}")

    success_count = 0
    bytes_moved = 0
    start = time.time()

    # Walk the entire source
    for root, dirs, files in os.walk(SOURCE_ROOT):
        # SKIP JUNK FOLDERS
        if "node_modules" in root or "C-Panel" in root or ".Recycle" in root:
            continue

        for name in files:
            src_path = os.path.join(root, name)
            
            # 1. THE FILTER: Does this match our Project Keywords?
            if matches_keyword(src_path):
                
                # Calculate Destination (Preserve Folder Structure)
                rel_path = os.path.relpath(root, SOURCE_ROOT)
                dest_folder = os.path.join(DEST_ROOT, rel_path)
                dest_path = os.path.join(dest_folder, name)
                
                try:
                    if not os.path.exists(dest_folder):
                        os.makedirs(dest_folder)

                    # 2. IDEMPOTENCY (Don't copy if already safe)
                    if os.path.exists(dest_path):
                        if os.path.getsize(src_path) == os.path.getsize(dest_path):
                            continue # Skip
                    
                    # 3. COPY & VERIFY
                    shutil.copy2(src_path, dest_path)
                    
                    if get_hash(src_path) == get_hash(dest_path):
                        logging.info(f"✅ SECURED: {name}")
                        success_count += 1
                        bytes_moved += os.path.getsize(dest_path)
                    else:
                        logging.error(f"❌ HASH FAIL: {name}")
                        os.remove(dest_path)

                except Exception as e:
                    logging.error(f"❌ ERROR: {name} - {e}")
                    
            # Ticker
            if success_count % 50 == 0 and success_count > 0:
                 print(f"    Secured {success_count} project files... ({int(bytes_moved/1024/1024)} MB)")

    print("-" * 50)
    print(f"🏁 PROJECT MIGRATION COMPLETE")
    print(f"    Files Secured: {success_count}")
    print(f"    Volume: {(bytes_moved/1024/1024):.2f} MB")
    print(f"    Log: {LOG_FILE}")

if __name__ == "__main__":
    migrate_projects()
