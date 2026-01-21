import os
import email
from email.policy import default
import psycopg2
from datetime import datetime
import re

# --- CONFIGURATION ---
# Note: The path handles the brackets and spaces
TARGET_DIR = "/mnt/fortress_mail/@local/1026/1026/Maildir/.[Gmail].All Mail/cur"
DB_PASS = "190AntiochCemeteryRD!!!"

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, ' ', raw_html)
    return cleantext.replace('\n', ' ').replace('\r', '').strip()

def parse_email(file_path):
    try:
        with open(file_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=default)
        
        subject = msg['subject'] or "No Subject"
        sender = msg['from'] or "Unknown"
        date_str = msg['date']
        try:
            sent_at = email.utils.parsedate_to_datetime(date_str)
        except:
            sent_at = datetime.now()

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body += part.get_payload(decode=True).decode(errors='ignore')
                elif content_type == "text/html":
                    html_content = part.get_payload(decode=True).decode(errors='ignore')
                    body += clean_html(html_content)
        else:
            payload = msg.get_payload(decode=True).decode(errors='ignore')
            if msg.get_content_type() == "text/html":
                body = clean_html(payload)
            else:
                body = payload

        return subject, sender, sent_at, body
    except Exception:
        return None

def main():
    print(f"🛡️  Fortress Deep Archive Ingester")
    print(f"📂 Target: {TARGET_DIR}")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check total files first
    try:
        files = [f for f in os.listdir(TARGET_DIR) if os.path.isfile(os.path.join(TARGET_DIR, f))]
        total = len(files)
        print(f"🌊 Deep Archive Size: {total:,} emails detected.")
    except FileNotFoundError:
        print("❌ Error: Target directory not found. Check mount.")
        return

    print("🚀 Beginning Extraction (Append Mode)...")
    
    count = 0
    skipped = 0
    
    for filename in files:
        file_path = os.path.join(TARGET_DIR, filename)
        
        # KEY LOGIC: Check if this exact file is already in the DB to avoid duplicates
        cur.execute("SELECT id FROM email_archive WHERE file_path = %s", (file_path,))
        if cur.fetchone():
            skipped += 1
            if skipped % 1000 == 0:
                print(f"   ...skipped {skipped} duplicates")
            continue

        data = parse_email(file_path)
        if data:
            subject, sender, sent_at, body = data
            # Only ingest if valid text found
            if len(body) > 20: 
                try:
                    cur.execute("""
                        INSERT INTO email_archive (category, file_path, sender, subject, content, sent_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, ("Uncategorized Archive", file_path, sender, subject, body, sent_at))
                    count += 1
                    if count % 200 == 0:
                        print(f"   ...ingested {count} new records")
                        conn.commit()
                except Exception as e:
                    conn.rollback()
                    # Silent fail on individual record error to keep moving

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ MISSION COMPLETE. Added: {count}. Skipped (Duplicates): {skipped}.")

if __name__ == "__main__":
    main()
