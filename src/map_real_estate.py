import os
import psycopg2
import re
from collections import Counter

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


DB_PASS = _MINER_BOT_PASSWORD

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def main():
    print("\n🗺️  FORTRESS PROPERTY MAPPER")
    print("----------------------------")

    conn = get_db_connection()
    cur = conn.cursor()

    # Get all Real Estate text
    cur.execute("SELECT content FROM email_archive WHERE category = 'Real Estate Ops' OR category = 'Property Operations'")
    
    address_counter = Counter()
    
    # Regex for standard US addresses (e.g., 1234 Aska Rd)
    # Focusing on Blue Ridge/Aska area patterns and generic formatting
    pattern = re.compile(r'\b\d{3,5}\s+[A-Z][a-z]+\s+(?:Rd|Ln|Dr|St|Way|Ct|Ave|Blvd)\b')

    print("   Scanning documents for location data...")
    
    rows = cur.fetchall()
    print(f"   -> Processing {len(rows)} Real Estate records.")
    
    for row in rows:
        text = row[0]
        if text:
            matches = pattern.findall(text)
            for m in matches:
                # Clean up duplicates/spacing
                addr = m.strip()
                address_counter[addr] += 1

    print("\n🔥 PROPERTY HEATMAP (Most Active Locations):")
    print("-------------------------------------------")
    for addr, count in address_counter.most_common(25):
        print(f"   📍 {addr.ljust(30)} : {count} Alerts")

if __name__ == "__main__":
    main()
