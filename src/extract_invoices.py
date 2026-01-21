import os
import email
from email.policy import default
import psycopg2
import shutil
from datetime import datetime
import re

# --- CONFIGURATION ---
DB_PASS = "190AntiochCemeteryRD!!!"
OUTPUT_DIR = "/mnt/fortress_data/invoices"

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def sanitize(filename):
    # Remove weird characters to prevent file system errors
    return re.sub(r'[^\w\-_\. ]', '_', filename)

def main():
    print(f"🛡️  Fortress Invoice Hunter")
    print(f"📂 Extraction Target: {OUTPUT_DIR}")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print("   -> Created output directory.")

    conn = get_db_connection()
    cur = conn.cursor()

    # TARGETING: Only look at Construction Ops senders we identified
    sql = """
        SELECT file_path, sender, sent_at 
        FROM email_archive 
        WHERE category = 'Construction Ops' 
        AND (sender ILIKE '%411%' OR sender ILIKE '%garland%' OR sender ILIKE '%inspection%' OR sender ILIKE '%invoice%')
    """
    cur.execute(sql)
    rows = cur.fetchall()
    print(f"🎯 Scanning {len(rows)} candidate emails for attachments...")

    pdf_count = 0
    
    for row in rows:
        file_path = row[0]
        sender_raw = row[1]
        sent_date = row[2].strftime('%Y-%m-%d')
        
        # Clean sender name for the filename (e.g. "Luke Garland" instead of "Luke <luke@mail.com>")
        sender_clean = sanitize(sender_raw.split('<')[0].strip()[:20])

        try:
            with open(file_path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=default)

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get('Content-Disposition') is None:
                    continue

                filename = part.get_filename()
                if filename and (filename.lower().endswith('.pdf') or filename.lower().endswith('.csv')):
                    # BUILD THE ASSET NAME: Date_Contractor_OriginalName.pdf
                    new_name = f"{sent_date}_{sender_clean}_{sanitize(filename)}"
                    dest_path = os.path.join(OUTPUT_DIR, new_name)
                    
                    with open(dest_path, 'wb') as f_out:
                        f_out.write(part.get_payload(decode=True))
                    
                    print(f"   ✅ Extracted: {new_name}")
                    pdf_count += 1
        except Exception as e:
            # Silent fail on individual read errors
            pass

    conn.close()
    print(f"\n🚀 MISSION COMPLETE. Secured {pdf_count} invoice documents.")

if __name__ == "__main__":
    main()
