import os
import sqlite3
import shutil

# --- CONFIG ---
# 1. The CPanel Lab (Where domain emails live)
CPANEL_ROOT = "/mnt/fortress_nas/Enterprise_War_Room/Web_Lab/Exploded/mail"
# 2. The MailPlus Server (Deep Scan)
MAILPLUS_ROOT = "/mnt/vol1_source/System/MailPlus_Server"
# 3. The Master Index (To find Gmail zips)
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")

WAR_ROOM_COMMS = "/mnt/fortress_nas/Enterprise_War_Room/Communications/Deep_Discovery"

def hunt_cpanel_mail():
    print(f"🌐 DEEP DIVE: CPANEL SERVER MAIL ({CPANEL_ROOT})")
    if not os.path.exists(CPANEL_ROOT):
        print("   ❌ CPanel Mail folder not found. Did the explosion finish?")
        return

    # CPanel Structure: mail / domain / user / cur
    found_accounts = {}
    
    for root, dirs, files in os.walk(CPANEL_ROOT):
        # Look for the 'cur' folder (Standard Maildir storage for emails)
        if 'cur' in dirs:
            # The folder structure usually tells us the user
            # .../mail/cabin-rentals-of-georgia.com/barbara/cur
            parts = root.split(os.sep)
            try:
                # Find the domain part
                if "cabin-rentals-of-georgia.com" in parts:
                    idx = parts.index("cabin-rentals-of-georgia.com")
                    user = parts[idx + 1] # The folder after the domain is the user
                    
                    # Count emails
                    cur_path = os.path.join(root, 'cur')
                    count = len(os.listdir(cur_path))
                    
                    full_account = f"{user}@cabin-rentals-of-georgia.com"
                    if full_account not in found_accounts: found_accounts[full_account] = 0
                    found_accounts[full_account] += count
            except: pass

    if found_accounts:
        print(f"   ✅ FOUND BUSINESS ACCOUNTS (In CPanel Dump):")
        for acct, count in found_accounts.items():
            print(f"      📧 {acct:<40} | {count:,} emails")
    else:
        print("   ❌ No standard CPanel email accounts found.")

def hunt_gmail_takeout():
    print(f"\n📦 DEEP DIVE: GMAIL ARCHIVES (Google Takeout)")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Search for massive zips or mbox files that look like Google Takeout
    # Google Takeout files usually have 'takeout' or 'gmail' in the name
    c.execute("SELECT path, size FROM files WHERE (filename LIKE '%takeout%' OR filename LIKE '%gmail%') AND (extension='.zip' OR extension='.mbox')")
    results = c.fetchall()
    
    found = False
    for path, size in results:
        mb = size / (1024*1024)
        print(f"   🎁 FOUND ARCHIVE: {os.path.basename(path)} ({mb:.1f} MB)")
        print(f"      📍 {os.path.dirname(path)}")
        found = True
        
    if not found:
        print("   (No obvious 'Takeout' or 'Gmail' zip files found. Checking generic large zips...)")

def deep_mailplus_db():
    print(f"\n🗄️  DEEP DIVE: MAILPLUS DATABASES (No Depth Limit)")
    # Recursive walk looking for ANY database file inside MailPlus
    dbs = []
    for root, dirs, files in os.walk(MAILPLUS_ROOT):
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3', '.sql', '.postgres')):
                # Filter out tiny system dbs
                path = os.path.join(root, f)
                if os.path.getsize(path) > 1024*100: # > 100KB
                    dbs.append(path)
    
    if dbs:
        print(f"   Found {len(dbs)} internal databases. Top 5 largest:")
        dbs.sort(key=lambda x: os.path.getsize(x), reverse=True)
        for d in dbs[:5]:
            print(f"      💾 {os.path.basename(d)} ({os.path.getsize(d)/1024/1024:.1f} MB)")
            print(f"         └─ {os.path.dirname(d)}")

if __name__ == "__main__":
    hunt_cpanel_mail()
    hunt_gmail_takeout()
    deep_mailplus_db()
