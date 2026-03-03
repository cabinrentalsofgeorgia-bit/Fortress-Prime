import os
import psycopg2
import pandas as pd

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "fortress_db"),
        user=os.getenv("DB_USER", "miner_bot"),
        password=os.getenv("DB_PASS", ""),
    )

def run_query(query, params=None):
    conn = get_connection()
    try:
        return pd.read_sql(query, conn, params=params) if params else pd.read_sql(query, conn)
    finally:
        conn.close()