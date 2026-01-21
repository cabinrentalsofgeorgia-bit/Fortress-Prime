import mailbox
import email
from email import policy
from bs4 import BeautifulSoup
import psycopg2
import requests
import os
import sys
from datetime import datetime

# --- CONFIGURATION ---
NAS_PATH = "/mnt/nas_archive"
DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password"

# Worker (Spark 1)
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def clean_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=' ', strip=True)

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            try:
                content_type = part.get_content_type()
                if part.get_content_disposition() == 'attachment': continue
                payload = part.get_payload(decode=True)
                if not payload: continue
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
        # Basic parsing, can be improved for edge cases
        return email.utils.parsedate_to_datetime(date_str)
    except:
        return datetime.now()

def mine_emails():
    print(f"[*] Connecting to Vault at {DB_HOST}...")
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = conn.cursor()
    
    print(f"[*] Scanning NAS Path: {NAS_PATH}...")
    for root, dirs, files in os.walk(NAS_PATH):
        for file in files:
            if file.endswith(".mbox") or file.endswith(".eml"):
                file_path = os.path.join(root, file)
                print(f"\nProcessing Archive: {file}...")
                
                # Check duplication
                cursor.execute("SELECT id FROM market_intel WHERE source_file = %s LIMIT 1", (file,))
                if cursor.fetchone():
                    print(" -> Already Indexed. Skipping.")
                    continue

                try:
                    if file.endswith(".mbox"):
                        mbox = mailbox.mbox(file_path)
                        messages = mbox
                    else:
                        continue # Skip single .eml for now unless requested

                    batch_count = 0
                    for message in messages:
                        subject = message['subject'] or "No Subject"
                        sender = message['from'] or "Unknown"
                        sent_at = parse_date(message['date'])
                        
                        content = extract_body(message)
                        if len(content) < 150: continue 

                        # Chunking
                        full_text = f"Date: {sent_at}\nFrom: {sender}\nSubject: {subject}\n\n{content}"
                        chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000)]
                        
                        for idx, chunk in enumerate(chunks):
                            try:
                                resp = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": chunk})
                                if resp.status_code == 200:
                                    vec = resp.json()['embedding']
                                    
                                    # THE UPGRADE: Inserting into new columns
                                    cursor.execute("""
                                        INSERT INTO market_intel 
                                        (source_file, chunk_index, content, embedding, sender, subject_line, sent_at) 
                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                    """, (file, idx, chunk, vec, sender, subject, sent_at))
                            except Exception as e:
                                pass

                        batch_count += 1
                        if batch_count % 10 == 0:
                            conn.commit()
                            sys.stdout.write(f"\r -> Indexed {batch_count} emails from {file}...")
                            sys.stdout.flush()

                    conn.commit()
                except Exception as e:
                    print(f"Error reading file {file}: {e}")

    conn.close()
    print("\n[+] Mining Complete.")

if __name__ == "__main__":
    mine_emails()
