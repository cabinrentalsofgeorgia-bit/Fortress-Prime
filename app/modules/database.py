import psycopg2
import pandas as pd

def get_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password="190AntiochCemeteryRB!!!")

def run_query(query, params=None):
    conn = get_connection()
    try:
        return pd.read_sql(query, conn, params=params) if params else pd.read_sql(query, conn)
    finally:
        conn.close()