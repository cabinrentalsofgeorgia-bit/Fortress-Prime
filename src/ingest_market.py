import os
import email
from email.policy import default
import psycopg2
from datetime import datetime
import re

# --- CONFIGURATION ---
TARGET_DIR = "/mnt/fortress_mail/@local/1026/1026/Maildir/.MARKET_INTELLIGENCE/cur"
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def clean_html(raw_html):
    # Aggressively strip HTML tags to extract readable English text
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
        # Enterprise Logic: Check ALL parts of the email for text
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body += part.get_payload(decode=True).decode(errors='ignore')
                elif content_type == "text/html":
                    # Convert HTML to Text
                    html_content = part.get_payload(decode=True).decode(errors='ignore')
                    body += clean_html(html_content)
        else:
            # Handle single-part emails
            payload = msg.get_payload(decode=True).decode(errors='ignore')
            if msg.get_content_type() == "text/html":
                body = clean_html(payload)
            else:
                body = payload

        return subject, sender, sent_at, body
    except Exception as e:
        return None

def main():
    print(f"🛡️  Fortress Market Ingester (Enterprise HTML)")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create the Enterprise Schema (with Full Text Search)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_archive (
            id SERIAL PRIMARY KEY,
            category TEXT,
            file_path TEXT UNIQUE,
            sender TEXT,
            subject TEXT,
            content TEXT,
            sent_at TIMESTAMP,
            ts tsvector GENERATED ALWAYS AS (to_tsvector('english', subject || ' ' || content)) STORED
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_email_ts ON email_archive USING GIN(ts);")
    conn.commit()
    
    files = [f for f in os.listdir(TARGET_DIR) if os.path.isfile(os.path.join(TARGET_DIR, f))]
    total = len(files)
    print(f"🔄 Processing {total:,} emails...")
    
    count = 0
    for filename in files:
        file_path = os.path.join(TARGET_DIR, filename)
        
        # Optimization: Skip if already exists
        cur.execute("SELECT id FROM email_archive WHERE file_path = %s", (file_path,))
        if cur.fetchone():
            continue

        data = parse_email(file_path)
        if data:
            subject, sender, sent_at, body = data
            if len(body) > 50: # Only save if we actually found real text
                cur.execute("""
                    INSERT INTO email_archive (category, file_path, sender, subject, content, sent_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, ("Market Intelligence", file_path, sender, subject, body, sent_at))
                count += 1
                if count % 500 == 0:
                    print(f"   ...extracted {count} signals")
                    conn.commit()

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ DONE. Extracted readable text from {count} emails.")

if __name__ == "__main__":
    main()
