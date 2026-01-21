import psycopg2

try:
    # Connect (VS Code handles the '!!!' safely)
    conn = psycopg2.connect(
        host='localhost', 
        database='fortress_db', 
        user='miner_bot', 
        password='190AntiochCemeteryRD!!!'
    )
    cur = conn.cursor()
    
    # Create the Missing Table
    sql = """
    CREATE TABLE IF NOT EXISTS node_telemetry (
        node_name TEXT PRIMARY KEY, 
        last_seen TIMESTAMP, 
        gpu_temp FLOAT, 
        gpu_load FLOAT, 
        vram_usage TEXT
    );
    """
    cur.execute(sql)
    conn.commit()
    print("✅ DATABASE TABLE CREATED SUCCESSFULLY")
    conn.close()

except Exception as e:
    print(f"❌ Error: {e}")