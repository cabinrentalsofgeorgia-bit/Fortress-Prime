"""
FORTRESS PRIME — Retina Upgrade: Visual Hashing (pHash)
========================================================
Adds the visual_hash column to ops_visuals for perceptual deduplication.
This allows the Vision Engine to skip images it has already "seen",
even if they live at different file paths (thumbnails, copies, etc.).
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv("/home/admin/Fortress-Prime/.env")

def upgrade_retina():
    print("🧬 Upgrading Retina with Visual Hashing...")
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME", "fortress_db"),
        user=os.getenv("DB_USER", "miner_bot"),
        password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )
    cur = conn.cursor()

    try:
        # Add the hash column
        cur.execute("ALTER TABLE ops_visuals ADD COLUMN IF NOT EXISTS visual_hash VARCHAR(64);")

        # Create an index for fast duplicate checking
        cur.execute("CREATE INDEX IF NOT EXISTS idx_visual_hash ON ops_visuals(visual_hash);")

        conn.commit()
        print("✅ Retina Upgraded. Ready for De-Duplication.")
    except Exception as e:
        print(f"⚠️ Upgrade Error (Maybe already exists): {e}")
        conn.rollback()

    conn.close()

if __name__ == "__main__":
    upgrade_retina()
