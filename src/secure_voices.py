import sqlite3
import os
import shutil
import logging

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
WAR_ROOM_COMMS = "/mnt/fortress_nas/Enterprise_War_Room/Communications"
LOG_FILE = os.path.expanduser("~/Fortress-Prime/secure_voices.log")

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

def secure_assets():
    print(f"🗣️  SECURING THE VOICES (Texts & Emails)...")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. SECURE TAYLOR'S MAILPLUS
    # We found it in the previous step, so we pull it by path pattern
    print("\n📧 ARCHIVING TAYLOR'S MAILPLUS...")
    src_root = "/mnt/vol1_source/System/MailPlus_Server"
    dest_root = os.path.join(WAR_ROOM_COMMS, "MailPlus_Taylor")
    
    count = 0
    # Walk the MailPlus folder specifically looking for Taylor
    for root, dirs, files in os.walk(src_root):
        if "taylor" in root.lower():
            for f in files:
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, src_root)
                dest = os.path.join(dest_root, rel_path)
                try:
                    if not os.path.exists(os.path.dirname(dest)): os.makedirs(os.path.dirname(dest))
                    shutil.copy2(src, dest)
                    count += 1
                except: pass
    print(f"   ✅ Secured {count:,} items for Taylor.")

    # 2. SECURE THE CHAT.DB (iMessages)
    print("\n💬 SECURING iMESSAGE HISTORIES (Gary's Voice)...")
    c.execute("SELECT path, size FROM files WHERE filename='chat.db' OR filename='TableDB.db'") # TableDB is often the attachment index
    chats = c.fetchall()
    
    dest_chat = os.path.join(WAR_ROOM_COMMS, "iMessage_Archives")
    if not os.path.exists(dest_chat): os.makedirs(dest_chat)
    
    for src, size in chats:
        # Create a unique name based on parent folder to avoid overwriting duplicates
        parent = os.path.basename(os.path.dirname(src))
        grandparent = os.path.basename(os.path.dirname(os.path.dirname(src)))
        new_name = f"chat_{grandparent}_{parent}.db"
        
        dest = os.path.join(dest_chat, new_name)
        try:
            shutil.copy2(src, dest)
            print(f"   ✅ Secured: {new_name} ({size/1024/1024:.1f} MB)")
        except Exception as e:
            print(f"   ❌ Failed: {src} - {e}")

    # 3. SECURE SAFARI HISTORY
    print("\n🌍 SECURING BROWSER HISTORY...")
    c.execute("SELECT path FROM files WHERE filename='History.db' OR filename='SafariTabs.db'")
    history = c.fetchall()
    dest_hist = os.path.join(WAR_ROOM_COMMS, "Browser_Forensics")
    if not os.path.exists(dest_hist): os.makedirs(dest_hist)
    
    for row in history:
        src = row[0]
        name = f"Safari_{os.path.basename(os.path.dirname(src))}_{os.path.basename(src)}"
        try:
            shutil.copy2(src, os.path.join(dest_hist, name))
            print(f"   ✅ Secured: {name}")
        except Exception as e:
            print(f"   ❌ Failed: {src} - {e}")

    conn.close()

if __name__ == "__main__":
    secure_assets()
