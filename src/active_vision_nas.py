import os
import time
import psycopg2
import socket
import sys

# CONFIG
DB_HOST = "192.168.0.100"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
IMAGE_DIR = "/mnt/fortress_ai/raw_images"

def get_db():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

print(f"👁️  NAS VISION AGENT ACTIVE on {socket.gethostname()}")
print(f"📂 Watching: {IMAGE_DIR}")

try:
    # 1. Check if we can see the files
    if not os.path.exists(IMAGE_DIR):
        print(f"❌ ERROR: Cannot find {IMAGE_DIR}. Is the NAS mounted?")
        sys.exit(1)

    all_files = [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    print(f"📸 Found {len(all_files)} images in the vault.")

    # 2. Connect to DB
    conn = get_db()
    cur = conn.cursor()
    # Ensure table exists
    cur.execute("CREATE TABLE IF NOT EXISTS images (id SERIAL PRIMARY KEY, filename TEXT UNIQUE, ai_description TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    conn.commit()
    
    # 3. Process Loop (Batch of 100)
    count = 0
    for img in all_files:
        if count >= 100: break 
        
        # Check if already processed
        cur.execute("SELECT id FROM images WHERE filename = %s", (img,))
        if cur.fetchone():
            continue 

        # Simulate GPU Work
        print(f"   [GPU] Analyzing {img}...")
        time.sleep(0.05) 
        
        # Insert Data
        desc = f"Analyzed on Spark-1 (NAS Source). File: {img}"
        cur.execute("INSERT INTO images (filename, ai_description) VALUES (%s, %s)", (img, desc))
        conn.commit()
        count += 1
        
    print(f"✅ BATCH COMPLETE: Processed {count} new images.")
    conn.close()

except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}")
