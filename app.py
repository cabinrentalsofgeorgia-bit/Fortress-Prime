import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
import time

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Fortress Legal v4", page_icon="🛡️", layout="wide")

# --- 2. DATABASE CONNECTION ---
try:
    # CONNECTING WITHOUT PROXY
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error(f"❌ Connection Error: {e}")
    st.stop()

# --- 3. DATA FETCHING ---
def get_system_health():
    try:
        response = supabase.table("system_health").select("*").execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['last_updated'] = pd.to_datetime(df['last_updated'])
            return df.sort_values(by="last_updated", ascending=False).drop_duplicates(subset=["node_id"], keep="first")
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. DASHBOARD UI ---
st.title("🛡️ Fortress Legal: Enterprise Cluster")
st.markdown("---")

tab1, tab2 = st.tabs(["📊 Hardware", "📝 Legal AI"])

with tab1:
    if st.button("🔄 Refresh"): st.rerun()
    
    node_data = get_system_health()
    if node_data.empty:
        st.warning("⚠️ Waiting for Spark Signals...")
    else:
        cols = st.columns(len(node_data))
        for index, (i, row) in enumerate(node_data.iterrows()):
            with cols[index % len(cols)]:
                with st.expander(f"{'⚓' if '2' in row['node_id'] else '🔥'} {row['node_id']}", expanded=True):
                    st.metric("Temp", f"{row['gpu_temp']}°C")
                    st.metric("VRAM", f"{row['vram_used']} MB")
                    st.progress(int(row['gpu_util']), text="GPU Load")

with tab2:
    st.info("System Online. Ready for Document Ingestion.")
    st.text_input("Query Case Files")
    if st.button("Analyze"): st.warning("No documents found.")
