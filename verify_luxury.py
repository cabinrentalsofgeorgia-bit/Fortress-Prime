import os
import psycopg2


_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")
DB_PASS = _MINER_BOT_PASSWORD

try:
    conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)
    cur = conn.cursor()

    print("[*] SEARCHING FOR 'BLUE RIDGE LUXURY' ASSETS...")

    # Check Titles
    cur.execute("SELECT subject_line, content FROM market_intel WHERE subject_line ILIKE '%Luxury%' OR content ILIKE '%Blue Ridge Luxury%'")
    results = cur.fetchall()

    if not results:
        print("[!] No direct match found. Checking related Landing Pages...")
        # Check for "Special Landing Pages" we recovered
        cur.execute("SELECT subject_line FROM market_intel WHERE content LIKE '%TYPE: SPECIAL LANDING PAGE%'")
        landings = cur.fetchall()
        for l in landings:
            print(f" -> Found Landing Page: {l[0]}")
    else:
        print(f"[+] SUCCESS. Found {len(results)} matching assets:")
        for subject, content in results:
            print(f" -> {subject}")
            # Print a snippet to verify it's the right text
            start = content.find("Blue Ridge Luxury")
            if start != -1:
                print(f"    Snippet: \"...{content[start:start+100]}...\"")

    conn.close()
except Exception as e:
    print(e)
