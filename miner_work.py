import os
import email
from email import policy
from email.parser import BytesParser
import requests
import psycopg2
import sys
from datetime import datetime

# --- CONFIGURATION ---
# TARGET: The ".Work" folder you found
MAIL_ROOT = "/mnt/nas/mail/@local/1026/1026/Maildir/.Work"

DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password"
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def get_embedding(text):
    try:
        response = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": text}, timeout=30)
        if response.status_code == 200:
            return response.json()["embedding"]
    except: return None
    return None

def process_emails():
    print(f"[*] Connecting to Vault...")
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = conn.cursor()
    
    # Maildir structure has 'cur' (current) and 'new' folders
    target_dirs = [os.path.join(MAIL_ROOT, "cur"), os.path.join(MAIL_ROOT, "new")]
    
    print(f"[*] Special Ops: Scanning .Work Folder...")

    count = 0
    for directory in target_dirs:
        if not os.path.exists(directory): continue
        
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            
            # Skip if already mined
            cursor.execute("SELECT id FROM market_intel WHERE source_file = %s LIMIT 1", (filename,))
            if cursor.fetchone(): continue

            try:
                with open(filepath, "rb") as f:
                    msg = BytesParser(policy=policy.default).parse(f)
                
                # Extract Content
                body = msg.get_body(preferencelist=('plain', 'html'))
                content = body.get_content() if body else ""
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", "Unknown")
                
                # Sanitize text
                content = content.replace('\x00', '')
                
                # Create Embedding
                full_text = f"Subject: {subject}\nFrom: {sender}\n\n{content[:2000]}"
                vector = get_embedding(full_text)

                if vector:
                    # Tag subject with [WORK] for clarity
                    cursor.execute("""
                        INSERT INTO market_intel (source_file, content, embedding, sender, subject_line, sent_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (filename, content[:5000], vector, sender, f"[WORK] {subject}", datetime.now()))
                    conn.commit()
                    count += 1
                    print(f" -> Secured: {subject[:40]}...")

            except Exception as e:
                continue

    conn.close()
    print(f"\n[+] Special Ops Complete. Items Secured: {count}")

if __name__ == "__main__":
    process_emails()
