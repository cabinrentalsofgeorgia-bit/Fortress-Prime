import time
import random
import os
import psycopg2
from datetime import datetime

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=_MINER_BOT_PASSWORD)
cur = conn.cursor()

print("📈 MARKET FEEDER ACTIVE (Press Ctrl+C to stop)...")
symbols = ['BTC-USD', 'NVDA', 'TSLA', 'MSTR']

try:
    while True:
        sym = random.choice(symbols)
        price = random.uniform(100, 90000)
        # Insert Fake Signal
        cur.execute("INSERT INTO market_signals (symbol, price, source) VALUES (%s, %s, %s)", (sym, price, 'Simulated Feed'))
        conn.commit()
        print(f"   [SIGNAL] {sym}:  -> Saved to DB")
        time.sleep(2)
except KeyboardInterrupt:
    print("🛑 FEEDER PAUSED.")
