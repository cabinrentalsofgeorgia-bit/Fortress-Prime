import streamlit as st
import pandas as pd
import psycopg2
import subprocess
import os

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


st.set_page_config(layout="wide")
st.title("Fortress Prime")

def get_conn(): return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=_MINER_BOT_PASSWORD)

t1, t2, t3 = st.tabs(["Signals", "System", "Audit"])

with t1:
    try:
        c = get_conn()
        st.dataframe(pd.read_sql("SELECT sent_at, subject FROM email_archive WHERE category='Market Intelligence' ORDER BY sent_at DESC LIMIT 5", c))
        c.close()
    except: st.error("DB Error")

with t2:
    st.success("SYSTEM ONLINE")
    if st.button("Check GPU", key="gpu"):
        try: st.code(subprocess.check_output("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader", shell=True).decode())
        except: st.write("No GPU")
    
    c1, c2 = st.columns(2)
    if c1.button("Run Signal Hunter"):
         subprocess.Popen(["/home/admin/miniforge3/bin/python", "/home/admin/fortress-prime/src/extract_trade_signals_v2.py"])
         st.info("Hunting...")
    if c2.button("Run Property Map"):
         subprocess.Popen(["/home/admin/miniforge3/bin/python", "/home/admin/fortress-prime/src/map_real_estate.py"])
         st.info("Mapping...")

    try: st.code(open("/home/admin/fortress-prime/PROJECT_MANIFEST.md").read())
    except: st.write("No Manifest")

with t3:
    if st.button("Run Audit"):
        st.code(subprocess.check_output("/home/admin/miniforge3/bin/python /home/admin/fortress-prime/src/analyze_spend.py", shell=True).decode())