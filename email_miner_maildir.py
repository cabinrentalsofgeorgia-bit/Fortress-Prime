import os
import email
from email import policy
from bs4 import BeautifulSoup
import psycopg2
import requests
import sys
from datetime import datetime

# --- CONFIGURATION ---
# The Root where we found the folders
MAIL_ROOT = "/mnt/nas/mail/@local/1026/1026/Maildir"

# The High-Value Targets (Folders to mine)
TARGET_FOLDERS = [
    ".MARKET_INTELLIGENCE",
    ".Market Insights",
    ".[Gmail].All Mail"  # The big one (Saved for last in the loop)
]

DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password"
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def clean_html(html_content):
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator=' ', strip=True)
    except:
        return html_content

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            try:
                content_type = part.get_content_type()
                if part.get_content_disposition() == 'attachment': continue
                payload = part.get_payload(decode=True)
                if not payload: continue
                
                # Decode bytes to string
                payload = payload.decode(errors='ignore')
                
                if content_type == "text/plain":
                    body += payload
                elif content_type == "text/html":
                    body += clean_html(payload)
            except:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                payload = payload.decode(errors='ignore')
                if msg.get_content_type() == "text/html":
                    body = clean_html(payload)
                else:
                    body = payload
        except:
            pass
    return body

def parse_date(date_str):
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except:
        return datetime.now()

def mine_maildir():
    print(f"[*] Connecting to Vault at {DB_HOST}...")
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = conn.cursor()

    for folder in TARGET_FOLDERS:
        # Construct the full path (handling Synology's dot naming)
        folder_path = os.path.join(MAIL_ROOT, folder)
        
        # Maildir stores emails in 'cur' (current) and 'new' (unread) subfolders
        subdirs = ['cur', 'new']
        
        print(f"\n[*] Targeted Sector: {folder}")
        
        if not os.path.exists(folder_path):
            print(f" -> Warning: Folder not found: {folder_path}")
            continue

        count = 0
        for subdir in subdirs:
            full_path = os.path.join(folder_path, subdir)
            if not os.path.exists(full_path): continue
            
            # Scan every file in the directory
            files = os.listdir(full_path)
            total_files = len(files)
            print(f" -> Scanning {subdir}/ ({total_files} files)...")

            for filename in files:
                file_path = os.path.join(full_path, filename)
                
                # Check duplication (Fast Skip)
                # We use the filename as the unique ID since Maildir names are unique
                cursor.execute("SELECT id FROM market_intel WHERE source_file = %s LIMIT 1", (filename,))
                if cursor.fetchone():
                    continue

                try:
                    with open(file_path, 'rb') as f:
                        msg = email.message_from_binary_file(f, policy=policy.default)
                    
                    sender = str(msg['from'])
                    subject = str(msg['subject'])
                    sent_at = parse_date(msg['date'])
                    content = extract_body(msg)

                    if len(content) < 200: continue # Skip short notifications

                    # Vectorize & Store
                    full_text = f"Date: {sent_at}\nFrom: {sender}\nSubject: {subject}\n\n{content}"
                    chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000)]
                    
                    for idx, chunk in enumerate(chunks):
                        resp = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": chunk})
                        if resp.status_code == 200:
                            vec = resp.json()['embedding']
                            cursor.execute("""
                                INSERT INTO market_intel 
                                (source_file, chunk_index, content, embedding, sender, subject_line, sent_at) 
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (filename, idx, chunk, vec, sender, subject, sent_at))
                    
                    count += 1
                    if count % 10 == 0:
                        conn.commit()
                        sys.stdout.write(f"\r -> Ingested {count} / {total_files} emails...")
                        sys.stdout.flush()

                except Exception as e:
                    # Silently skip errors to keep moving
                    pass
        
        conn.commit()
        print(f"\n[+] Completed Sector: {folder}")

    conn.close()
    print("\n[+] All Targets Secured.")

if __name__ == "__main__":
    mine_maildir()
