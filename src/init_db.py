import os
import psycopg2

DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))
if not DB_PASSWORD:
    raise ValueError("CRITICAL: DB_PASSWORD or DB_PASS not found in environment. "
                     "Set it in .env or export it before running this script.")

try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "fortress_db"),
        user=os.getenv("DB_USER", "miner_bot"),
        password=DB_PASSWORD,
    )
    cur = conn.cursor()

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
    print("DATABASE TABLE CREATED SUCCESSFULLY")
    conn.close()

except Exception as e:
    print(f"Error: {e}")