import os
import psycopg2
import pypdf
import sys

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# --- CONFIGURATION ---
DB_PASS = _MINER_BOT_PASSWORD
LEGAL_PATH = "/mnt/fortress_data/legal_archive"
BUSINESS_PATH = "/mnt/fortress_data/documents/Cabin Rentals Of Georgia"
# We scan the root documents for Knight specific business folders too
BUSINESS_PATH_2 = "/mnt/fortress_data/documents/knight/Documents/CABIN RENTALS OF GA"
EMAIL_PATH = "/mnt/fortress_data/documents/knight/Library/Mail/V2"

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def extract_text_from_pdf(filepath):
    try:
        reader = pypdf.PdfReader(filepath)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted: text += extracted + "\n"
        return text.replace('\x00', '') # Sanitize Poison Pills
    except:
        return ""

def ingest_folder(path, table_name, category_mode="folder"):
    print(f"🚀 Starting Ingest: {path} -> Table: {table_name}")
    if not os.path.exists(path):
        print(f"⚠️ Path not found: {path}")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    count = 0
    
    for dirpath, dirnames, filenames in os.walk(path):
        pdfs = [f for f in filenames if f.lower().endswith('.pdf')]
        for pdf in pdfs:
            full_path = os.path.join(dirpath, pdf)
            
            # Idempotency Check
            cur.execute(f"SELECT id FROM {table_name} WHERE file_path = %s", (full_path,))
            if cur.fetchone(): continue 
            
            if count % 20 == 0: print(f"   📖 Reading: {pdf[:40]}...")
            
            content = extract_text_from_pdf(full_path)
            if content:
                try:
                    cat = os.path.basename(dirpath) if category_mode == "folder" else "General"
                    cur.execute(f"INSERT INTO {table_name} (file_path, category, content) VALUES (%s, %s, %s)", 
                               (full_path, cat, content))
                    conn.commit()
                    count += 1
                except:
                    conn.rollback()
    
    print(f"✅ Ingest Complete for {table_name}: {count} new docs.")
    conn.close()

if __name__ == "__main__":
    # 1. Legal Wing
    ingest_folder(LEGAL_PATH, "legal_intel")
    
    # 2. Business Wing (Cabin Rentals)
    print("-" * 40)
    ingest_folder(BUSINESS_PATH, "business_intel")
    ingest_folder(BUSINESS_PATH_2, "business_intel")

    # 3. Email/Market Wing (Skipping for now if you want to prioritize Business)
    # Uncomment to run email ingest again:
    # ingest_email_archives() 
