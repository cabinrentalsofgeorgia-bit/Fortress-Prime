import os
import psycopg2

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


try:
    # Connect (VS Code handles the '!!!' safely)
    conn = psycopg2.connect(
        host='localhost', 
        database='fortress_db', 
        user='miner_bot', 
        password=_MINER_BOT_PASSWORD
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