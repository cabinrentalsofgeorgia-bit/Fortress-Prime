import os
import psycopg2
import psycopg2.extras
import pypdf
import sys

# --- CONFIGURATION ---
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
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
    if not os.path.exists(path):
        print(f"Path not found: {path}")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    all_pdfs = []
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            if f.lower().endswith('.pdf'):
                all_pdfs.append((os.path.join(dirpath, f), os.path.basename(dirpath)))

    if not all_pdfs:
        conn.close()
        return

    paths = [p[0] for p in all_pdfs]
    cur.execute(
        f"SELECT file_path FROM {table_name} WHERE file_path = ANY(%s)",
        (paths,)
    )
    existing = {row[0] for row in cur.fetchall()}

    count = 0
    batch = []
    for full_path, folder in all_pdfs:
        if full_path in existing:
            continue

        content = extract_text_from_pdf(full_path)
        if content:
            cat = folder if category_mode == "folder" else "General"
            batch.append((full_path, cat, content[:500000]))

            if len(batch) >= 50:
                psycopg2.extras.execute_batch(
                    cur,
                    f"INSERT INTO {table_name} (file_path, category, content) VALUES (%s, %s, %s)",
                    batch,
                )
                conn.commit()
                count += len(batch)
                batch = []

    if batch:
        psycopg2.extras.execute_batch(
            cur,
            f"INSERT INTO {table_name} (file_path, category, content) VALUES (%s, %s, %s)",
            batch,
        )
        conn.commit()
        count += len(batch)

    print(f"Ingest complete: {count} new docs")
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
