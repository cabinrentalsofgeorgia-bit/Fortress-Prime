import subprocess
import os
import logging
import time

# --- CONFIG ---
WAR_ROOM_COMMS = "/mnt/fortress_nas/Enterprise_War_Room/Communications"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/migration_voices.log")

# SOURCE MAP — Corrected to actual discovered paths
MIGRATION_TARGETS = [
    # PHASE 1: The Raw Backups (Single large files — fastest to move)
    {
        "src": "/mnt/vol1_source/System/MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/RAW_EMAIL_DUMP/download_cabinre_1769884761_36263.tar.gz",
        "dest": "Raw_Backups/",
        "type": "file",
        "label": "CPanel Full Archive (15 GB)"
    },
    {
        "src": "/mnt/vol1_source/System/MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/RAW_EMAIL_DUMP/download_cabinre_1769945883_38809.tar.gz",
        "dest": "Raw_Backups/",
        "type": "file",
        "label": "CPanel Archive #2 (605 MB)"
    },
    # PHASE 2: The Enterprise Data Lake (Structured intelligence — 333K files)
    {
        "src": "/mnt/vol1_source/System/MailPlus_Server/ENTERPRISE_DATA_LAKE",
        "dest": "Enterprise_Data_Lake",
        "type": "folder",
        "label": "Enterprise Data Lake (333K files)"
    },
    # PHASE 3: The Million-File March — Gary's Apple Mail
    {
        "src": "/mnt/vol1_source/Personal/Documents/knight/Library/Mail/V2",
        "dest": "Apple_Mail_Gary_Legacy_V2",
        "type": "folder",
        "label": "Gary's Apple Mail (928K files)"
    },
    # PHASE 4: MailPlus User 1026 (179K emails)
    {
        "src": "/mnt/vol1_source/System/MailPlus_Server/@local",
        "dest": "MailPlus_Local_Accounts",
        "type": "folder",
        "label": "MailPlus Local Accounts (179K emails)"
    }
]

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

def run_rsync(src, dest_folder, label):
    """Uses rsync for robust massive file copying"""
    full_dest = os.path.join(WAR_ROOM_COMMS, dest_folder)
    os.makedirs(full_dest if os.path.isdir(src) else os.path.dirname(full_dest), exist_ok=True)

    print(f"\n🚀 PHASE: {label}")
    print(f"   FROM: {src}")
    print(f"   TO:   {full_dest}")
    
    start = time.time()
    
    # Rsync flags: -a (archive), --info=progress2 (overall progress)
    if os.path.isfile(src):
        cmd = ["rsync", "-a", "--info=progress2", src, full_dest]
    else:
        cmd = ["rsync", "-a", "--info=progress2", src + "/", full_dest]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = int(time.time() - start)
        
        if result.returncode == 0:
            print(f"   ✅ SUCCESS in {elapsed}s: {label}")
            logging.info(f"SUCCESS [{elapsed}s]: {label} | {src} -> {full_dest}")
        else:
            print(f"   ❌ FAILED (code {result.returncode}): {result.stderr[:200]}")
            logging.error(f"FAILED: {label} | {result.stderr[:500]}")
    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
        logging.error(f"Exception for {src}: {e}")

def execute_migration():
    print(f"🏰 FORTRESS PRIME: OPERATION GRAND VOICE")
    print(f"   Target: {len(MIGRATION_TARGETS)} Major Archives")
    print(f"   Destination: {WAR_ROOM_COMMS}")
    print(f"   Log: {LOG_FILE}")
    
    total_start = time.time()
    
    for i, target in enumerate(MIGRATION_TARGETS, 1):
        print(f"\n{'='*60}")
        print(f"   [{i}/{len(MIGRATION_TARGETS)}]")
        
        if os.path.exists(target['src']):
            run_rsync(target['src'], target['dest'], target['label'])
        else:
            print(f"   ⚠️  MISSING SOURCE: {target['src']}")
            logging.warning(f"Source missing: {target['src']}")

    total_elapsed = int(time.time() - total_start)
    hours = total_elapsed // 3600
    minutes = (total_elapsed % 3600) // 60
    
    print(f"\n{'='*60}")
    print(f"🏁 OPERATION GRAND VOICE COMPLETE")
    print(f"   Total Time: {hours}h {minutes}m")
    print(f"   All Voices secured in: {WAR_ROOM_COMMS}")

if __name__ == "__main__":
    execute_migration()
