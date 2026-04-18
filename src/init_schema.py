import os
import psycopg2

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


try:
    # Connect to the Vault
    conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=_MINER_BOT_PASSWORD)
    cur = conn.cursor()
    
    print("🏗️  BUILDING DATABASE SCHEMA...")

    # 1. WAR ROOM TABLES (Pages & Images)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id SERIAL PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            content TEXT,
            last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            filename TEXT UNIQUE,
            path TEXT,
            alt_text TEXT,
            ai_description TEXT,
            processed BOOLEAN DEFAULT FALSE
        );
    """)
    print("   ✅ War Room Tables Created (pages, images)")

    # 2. FINANCIAL INTELLIGENCE TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_signals (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            price REAL,
            sentiment_score REAL,
            source TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    print("   ✅ Financial Table Created (market_signals)")

    conn.commit()
    conn.close()
    print("🎉 INITIALIZATION COMPLETE.")

except Exception as e:
    print(f"❌ ERROR: {e}")
