import os
import email
import email.policy
from email.parser import BytesParser
import requests
import psycopg2
import sys
import glob

# --- CONFIGURATION ---
# Base path where you extracted the emails
MAIL_ROOT = os.path.expanduser("~/fortress-prime/backup-1.18.2026_21-12-59_cabinre/homedir/mail/cabin-rentals-of-georgia.com/")

DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def get_embedding(text):
    if not text or len(text) < 10: return None
    try:
        response = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": text[:4000]}, timeout=10)
        if response.status_code == 200:
            return response.json()["embedding"]
    except: return None
    return None

def extract_body(msg):
    """ Extracts plain text body from email, ignoring HTML heavy parts if possible """
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get('Content-Disposition'))
            
            if ctype == 'text/plain' and 'attachment' not in cdispo:
                try:
                    body += part.get_content()
                except: pass
            elif ctype == 'text/html' and body == "":
                try:
                    body += part.get_content() # In production, strip HTML tags here
                except: pass
    else:
        try:
            body = msg.get_content()
        except: pass
    return body

def process_maildir():
    print(f"[*] TITAN MAIL: Scanning {MAIL_ROOT}...")
    
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        cursor = conn.cursor()
    except Exception as e:
        print(f"[!] DATABASE ERROR: {e}")
        return

    # Find all user directories (e.g., accounting, crog)
    if not os.path.exists(MAIL_ROOT):
        print(f"[!] ERROR: Path not found: {MAIL_ROOT}")
        return

    users = [d for d in os.listdir(MAIL_ROOT) if os.path.isdir(os.path.join(MAIL_ROOT, d))]
    
    total_emails = 0
    
    for user in users:
        # Ignore system folders
        if user.startswith("."): continue
        
        print(f" -> Processing Account: {user}...")
        
        # Check standard Maildir paths
        search_paths = [
            os.path.join(MAIL_ROOT, user, "cur"),
            os.path.join(MAIL_ROOT, user, "new")
        ]
        
        for folder in search_paths:
            if not os.path.exists(folder): continue
            
            # Scan files
            files = glob.glob(os.path.join(folder, "*"))
            for filepath in files:
                if not os.path.isfile(filepath): continue
                
                try:
                    with open(filepath, 'rb') as f:
                        msg = BytesParser(policy=email.policy.default).parse(f)
                    
                    sender = str(msg['from'])
                    subject = str(msg['subject'])
                    date = str(msg['date'])
                    body = extract_body(msg)
                    
                    if len(body) < 20: continue # Skip empty notifications
                    
                    # Deduplication check
                    cursor.execute("SELECT id FROM market_intel WHERE source_file = %s LIMIT 1", (os.path.basename(filepath),))
                    if cursor.fetchone(): continue
                    
                    # Create Record
                    full_record = f"""
TYPE: Business Email
FROM: {sender}
DATE: {date}
SUBJECT: {subject}
---
{body[:8000]}
"""
                    vector = get_embedding(full_record)
                    if vector:
                        # Truncate fields to fit DB limits just in case
                        clean_sender = sender[:254]
                        clean_subject = subject[:254] if subject else "No Subject"

                        cursor.execute("""
                            INSERT INTO market_intel (source_file, content, embedding, sender, subject_line, sent_at)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                        """, (os.path.basename(filepath), full_record, vector, clean_sender, clean_subject,))
                        conn.commit()
                        total_emails += 1
                        
                        if total_emails % 10 == 0:
                            print(f"    -> Indexed: {subject[:40]}...")

                except Exception as e:
                    continue

    print(f"\n[+] EMAIL MINING COMPLETE. Total Emails Secured: {total_emails}")
    conn.close()

if __name__ == "__main__":
    process_maildir()
