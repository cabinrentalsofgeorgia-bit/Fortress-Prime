import os
import psycopg2
import time
import random
import datetime

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# CONFIG
DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = _MINER_BOT_PASSWORD

# TRACKING LIST (Your Favorites)
tickers = {
    "BTC-USD": 95000.00,
    "NVDA": 135.50,
    "TSLA": 215.00,
    "MSTR": 1600.00
}

def get_db():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

# Setup Table
try:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_signals (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            price NUMERIC,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
except Exception as e:
    print(f"❌ DB Error: {e}")

print("🚀 MARKET AGENT ACTIVE. Streaming data...")

# Loop Forever
while True:
    try:
        conn = get_db()
        cur = conn.cursor()
        for symbol, price in tickers.items():
            # Simulate realistic fluctuation
            change = price * random.uniform(-0.005, 0.005)
            new_price = price + change
            tickers[symbol] = new_price 
            
            # Save to Vault
            cur.execute("INSERT INTO market_signals (symbol, price) VALUES (%s, %s)", (symbol, new_price))
        
        conn.commit()
        conn.close()
        time.sleep(5) # Update every 5 seconds
        
    except Exception as e:
        time.sleep(5)
