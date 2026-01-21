import time
import random
import psycopg2
from datetime import datetime

conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password="190AntiochCemeteryRD!!!")
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
