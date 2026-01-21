import os
import requests
import psycopg2
import sys
import time
# Try to import pypdf, handle if missing
try:
    from pypdf import PdfReader
except ImportError:
    print("Error: pypdf not installed. Run 'pip install pypdf' first.")
    sys.exit(1)
from datetime import datetime

# --- CONFIGURATION ---
TARGET_ROOT = "/mnt/nas/legal"

DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password"
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def extract_text_from_pdf(filepath):
    text = ""
    try:
        reader = PdfReader(filepath)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted
    except Exception as e:
        print(f" [!] Warning reading PDF {filepath}: {e}")
    # CLEANER: Removes NULL bytes that crash Postgres
    return text.replace('\x00', '')

def get_embedding(chunk, retry_count=3):
    """Robust embedding function with timeouts and retries"""
    for attempt in range(retry_count):
        try:
            # TIMEOUT: If Spark 1 takes >30s, retry
            resp = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": chunk}, timeout=30)
            if resp.status_code == 200:
                return resp.json()['embedding']
            else:
                pass
        except requests.exceptions.RequestException as e:
            # Network error or Timeout
            print(f" [!] AI Timeout. Retrying... ({attempt+1}/{retry_count})")
            time.sleep(2)
    return None

def mine_documents():
    print(f"[*] Connecting to Vault at {DB_HOST}...")
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        cursor = conn.cursor()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return
    
    print(f"[*] Scanning Legal Files in: {TARGET_ROOT}...")

    file_count = 0
    for root, dirs, files in os.walk(TARGET_ROOT):
        for file in files:
            if file.lower().endswith(('.pdf', '.txt', '.md', '.docx')):
                file_path = os.path.join(root, file)
                
                # Check Duplication
                cursor.execute("SELECT id FROM market_intel WHERE source_file = %s LIMIT 1", (file,))
                if cursor.fetchone():
                    continue

                print(f" -> Processing: {file}...")
                
                # Extract Text
                content = ""
                if file.lower().endswith('.pdf'):
                    content = extract_text_from_pdf(file_path)
                else:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            # CLEANER: Removes NULL bytes here too
                            content = f.read().replace('\x00', '')
                    except: continue

                if len(content) < 50: continue

                # Chunk & Embed
                sender = "Legal_Department"
                folder_name = os.path.basename(root)
                subject = f"[{folder_name}] {file}"
                sent_at = datetime.now() 

                chunks = [content[i:i+1000] for i in range(0, len(content), 1000)]
                
                for idx, chunk in enumerate(chunks):
                    vec = get_embedding(chunk)
                    if vec:
                        try:
                            cursor.execute("""
                                INSERT INTO market_intel 
                                (source_file, chunk_index, content, embedding, sender, subject_line, sent_at) 
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (file, idx, chunk, vec, sender, subject, sent_at))
                        except Exception as e:
                            print(f"Error saving to DB: {e}")
                            conn.rollback() # Reset DB transaction
                            continue
                
                file_count += 1
                conn.commit()

    conn.close()
    print(f"\n[+] Legal Ingestion Complete. Documents Secured: {file_count}")

if __name__ == "__main__":
    mine_documents()
