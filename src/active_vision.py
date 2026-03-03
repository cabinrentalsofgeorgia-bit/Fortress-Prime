import os
import time
import psycopg2
import random
import socket

# CONFIG: Connect back to Captain (Spark-2)
DB_HOST = "192.168.0.100"  # Captain's IP
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
IMAGE_DIR = "/home/admin/fortress-prime/images_to_process"

def get_db():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

print(f"👁️  VISION AGENT ACTIVE on {socket.gethostname()}")
print(f"📂 Scanning: {IMAGE_DIR}")

files = [f for f in os.listdir(IMAGE_DIR) if f.endswith('.jpg')]
print(f"📸 Found {len(files)} images to process.")

for img in files:
    try:
        # 1. Simulate GPU Processing (Replace with real Torch inference later)
        print(f"   [GPU] Analyzing {img}...")
        time.sleep(0.5) 
        
        # 2. Generate SEO Tags (Simulated)
        tags = ["rustic", "cabin", "luxury", "view", "vacation"]
        ai_desc = f"A beautiful {random.choice(tags)} scene in Blue Ridge, GA."
        
        # 3. Save to Captain's Vault
        conn = get_db()
        cur = conn.cursor()
        # Ensure table exists (just in case)
        cur.execute("CREATE TABLE IF NOT EXISTS images (id SERIAL PRIMARY KEY, filename TEXT, ai_description TEXT);")
        
        cur.execute("INSERT INTO images (filename, ai_description) VALUES (%s, %s)", (img, ai_desc))
        conn.commit()
        conn.close()
        print(f"   ✅ SAVED: {img}")
        
    except Exception as e:
        print(f"   ❌ ERROR on {img}: {e}")

print("🚀 BATCH COMPLETE.")
