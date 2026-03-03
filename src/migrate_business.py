import os
import shutil
import hashlib
import time
import logging

# --- MISSION CONFIG ---
SOURCE_DIR = "/mnt/vol1_source/Business"
DEST_DIR = "/mnt/fortress_nas/Business_Prime"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/migration_business.log")

# Setup Logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

def calculate_hash(filepath):
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(65536)
            if not data: break
            sha256.update(data)
    return sha256.hexdigest()

def migrate():
    print(f"🚀 STARTING MIGRATION: BUSINESS DATA")
    print(f"   From: {SOURCE_DIR}")
    print(f"   To:   {DEST_DIR}")
    
    success_count = 0
    fail_count = 0
    bytes_moved = 0
    start_time = time.time()

    for root, dirs, files in os.walk(SOURCE_DIR):
        # Create corresponding destination folder
        rel_path = os.path.relpath(root, SOURCE_DIR)
        dest_folder = os.path.join(DEST_DIR, rel_path)
        
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder)

        for name in files:
            # Filter Junk
            if name.startswith(".") or name.endswith(".tmp") or name == "Thumbs.db":
                continue

            src_file = os.path.join(root, name)
            dest_file = os.path.join(dest_folder, name)
            
            try:
                # 1. Check if already exists (Idempotency)
                if os.path.exists(dest_file):
                    if os.path.getsize(src_file) == os.path.getsize(dest_file):
                        logging.info(f"SKIPPED (Exists): {name}")
                        continue
                
                # 2. Copy
                shutil.copy2(src_file, dest_file)
                
                # 3. Verify Hash (The "Gold Standard" Check)
                src_hash = calculate_hash(src_file)
                dest_hash = calculate_hash(dest_file)
                
                if src_hash == dest_hash:
                    logging.info(f"✅ VERIFIED: {name}")
                    success_count += 1
                    bytes_moved += os.path.getsize(dest_file)
                else:
                    logging.error(f"❌ HASH MISMATCH: {name}")
                    os.remove(dest_file) # Safety delete
                    fail_count += 1

            except Exception as e:
                logging.error(f"❌ ERROR: {name} ({e})")
                fail_count += 1
                
            # Progress ticker
            if success_count % 50 == 0 and success_count > 0:
                print(f"   Moved {success_count} files... ({int(bytes_moved/1024/1024)} MB)")

    duration = time.time() - start_time
    print("-" * 40)
    print(f"🏁 MISSION COMPLETE")
    print(f"   Files Secured: {success_count}")
    print(f"   Volume: {bytes_moved / (1024**3):.2f} GB")
    print(f"   Time: {int(duration)} seconds")
    print(f"   Log: {LOG_FILE}")

if __name__ == "__main__":
    migrate()
