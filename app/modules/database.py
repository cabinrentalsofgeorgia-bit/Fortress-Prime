import os
import psycopg2
import pandas as pd

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")

def get_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=_MINER_BOT_PASSWORD)

def run_query(query, params=None):
    conn = get_connection()
    try:
        return pd.read_sql(query, conn, params=params) if params else pd.read_sql(query, conn)
    finally:
        conn.close()