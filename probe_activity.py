import psycopg2

# --- CONFIGURATION (Same as Titan) ---
DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password" # This matched your script settings

try:
    print(f"[*] Connecting to Vault as {DB_USER}...")
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = conn.cursor()
    
    # Query for the "Things to Do" we just mined
    print("[*] Searching for 'Things to Do' (Activity) pages...")
    cursor.execute("""
        SELECT subject_line, left(content, 300) 
        FROM market_intel 
        WHERE subject_line LIKE '%[ACTIVITY]%' 
        LIMIT 3;
    """)
    
    rows = cursor.fetchall()
    
    if not rows:
        print("[!] No Activity pages found yet. Titan might still be digging.")
    else:
        print(f"\n[+] SUCCESS! Found {len(rows)} Activity Pages:\n")
        for row in rows:
            print(f"SUBJECT: {row[0]}")
            print(f"PREVIEW: {row[1]}...")
            print("-" * 50)

    conn.close()

except Exception as e:
    print(f"[!] Connection Failed: {e}")
