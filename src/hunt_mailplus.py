import os
import sqlite3
import shutil

# --- CONFIG ---
MAILPLUS_ROOT = "/mnt/vol1_source/System/MailPlus_Server"
WAR_ROOM_COMMS = "/mnt/fortress_nas/Enterprise_War_Room/Communications/MailPlus_Archives"
WAR_ROOM_DBS = "/mnt/fortress_nas/Enterprise_War_Room/Databases/MailPlus_Internal"

# Target Accounts (The Voices)
TARGET_USERS = ["gary", "taylor", "lissa", "barbara", "cabin", "info", "admin"]

def deep_dive_mailplus():
    print(f"📧 INITIATING MAILPLUS FORENSICS...")
    print(f"    Target: {MAILPLUS_ROOT}")

    if not os.path.exists(MAILPLUS_ROOT):
        print("❌ CRITICAL: MailPlus folder not found. Check mount!")
        return

    # 1. MAP USER ACCOUNTS
    print("\n👥 MAPPING USER ACCOUNTS:")
    found_users = []
    
    # MailPlus usually stores mail in /domain/user or just /user
    # We walk the tree looking for user directories
    for root, dirs, files in os.walk(MAILPLUS_ROOT):
        # Don't go too deep yet
        if root.count(os.sep) - MAILPLUS_ROOT.count(os.sep) > 3: continue
        
        for d in dirs:
            # Check if directory matches a target user (loose match)
            if any(u in d.lower() for u in TARGET_USERS):
                user_path = os.path.join(root, d)
                # Count emails (files in cur/new/tmp often used in Maildir)
                email_count = 0
                for r, _, f in os.walk(user_path):
                    email_count += len(f)
                
                print(f"   👤 {d.upper()}: ~{email_count:,} items found.")
                found_users.append(user_path)

    # 2. HUNT DATABASES INSIDE MAILPLUS
    print("\n🗄️  HUNTING HIDDEN DATABASES (The Metadata)...")
    dbs_found = []
    for root, dirs, files in os.walk(MAILPLUS_ROOT):
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3', '.sql', '.postgres')):
                db_path = os.path.join(root, f)
                size_mb = os.path.getsize(db_path) / (1024*1024)
                print(f"   💾 FOUND DB: {f} ({size_mb:.2f} MB)")
                dbs_found.append(db_path)

    # 3. EXTRACTION
    print("\n🚚 SECURING ASSETS TO WAR ROOM...")
    
    # Copy Databases
    if dbs_found:
        if not os.path.exists(WAR_ROOM_DBS): os.makedirs(WAR_ROOM_DBS)
        for src in dbs_found:
            dest = os.path.join(WAR_ROOM_DBS, os.path.basename(src))
            try:
                shutil.copy2(src, dest)
                print(f"   ✅ Secured DB: {os.path.basename(src)}")
            except Exception as e:
                print(f"   ❌ Failed to copy {os.path.basename(src)}: {e}")

    # Copy User Archives (Structure Only - Optional Full Copy)
    # Note: Copying thousands of tiny files is slow. We flag them for now.
    if found_users:
        print(f"   ⚠️  Ready to copy {len(found_users)} user archives. (Run Phase 2 Copy for full transfer)")

if __name__ == "__main__":
    deep_dive_mailplus()
