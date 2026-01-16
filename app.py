import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
import time

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="Fortress Legal Command v5",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Supabase
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    DB_STATUS = "🟢 Online"
except Exception as e:
    DB_STATUS = f"🔴 Offline: {e}"

# --- 2. HELPER FUNCTIONS ---
def get_system_health():
    """Fetch live telemetry from Spark Cluster."""
    try:
        response = supabase.table("system_health").select("*").order("last_updated", desc=True).limit(20).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['last_updated'] = pd.to_datetime(df['last_updated'])
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def get_live_snapshot(df):
    """Get the single latest row for each node."""
    if df.empty: return df
    return df.sort_values(by="last_updated", ascending=False).drop_duplicates(subset=["node_id"], keep="first")

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("🛡️ Fortress Command")
    st.markdown("---")
    st.write(f"**Database:** {DB_STATUS}")
    st.write(f"**Cluster:** Spark-1 & Spark-2")
    st.markdown("---")
    
    st.subheader("⚙️ Active Models")
    st.caption("• GPT-4o (Reasoning)")
    st.caption("• Gemini 1.5 Pro (Context)")
    st.caption("• Text-Embedding-3 (Vector)")
    
    st.markdown("---")
    if st.button("🔄 Force Refresh"):
        st.rerun()

# --- 4. MAIN DASHBOARD ---
st.title("🛡️ Fortress Legal: Enterprise Cluster")

# Create 3 Tabs now: Hardware, Vault (Upload), Analysis (Chat)
tab1, tab2, tab3 = st.tabs(["📊 Live Telemetry", "📂 Document Vault", "🧠 Legal Analysis"])

# === TAB 1: HARDWARE MONITOR ===
with tab1:
    raw_df = get_system_health()
    snapshot = get_live_snapshot(raw_df)

    if snapshot.empty:
        st.warning("⚠️ Waiting for Spark Signals... (Check SSH)")
    else:
        # Top Level Aggregates
        col1, col2, col3, col4 = st.columns(4)
        avg_temp = snapshot['gpu_temp'].mean()
        total_vram = snapshot['vram_used'].sum()
        
        col1.metric("Cluster Status", "Active", "Connected")
        col2.metric("Avg GPU Temp", f"{avg_temp:.1f}°C")
        col3.metric("Total VRAM Used", f"{total_vram} MB")
        col4.metric("Active Nodes", len(snapshot))

        st.markdown("### 🖥️ Node Status")
        # Node Cards
        cols = st.columns(len(snapshot))
        for index, (i, row) in enumerate(snapshot.iterrows()):
            with cols[index % len(cols)]:
                # Visual Logic
                is_captain = "2" in row['node_id']
                icon = "⚓ CAPTAIN" if is_captain else "🔥 WORKER"
                color = "green" if row['gpu_temp'] < 80 else "red"
                
                with st.container(border=True):
                    st.subheader(f"{icon}")
                    st.write(f"**ID:** {row['node_id']}")
                    st.write(f"**Last Pulse:** {row['last_updated'].strftime('%H:%M:%S')}")
                    
                    st.divider()
                    
                    c1, c2 = st.columns(2)
                    c1.metric("Temp", f"{row['gpu_temp']}°C")
                    c2.metric("VRAM", f"{row['vram_used']} MB")
                    
                    st.caption("GPU Load")
                    st.progress(int(row['gpu_util']))

# === TAB 2: DOCUMENT VAULT (NEW!) ===
with tab2:
    st.header("📂 Legal Document Ingestion")
    st.info("Upload PDF case files here to train the AI.")
    
    uploaded_files = st.file_uploader("Drag & Drop Legal PDFs", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        st.success(f"Prepared {len(uploaded_files)} files for ingestion.")
        if st.button("🚀 Process & Vectorize (Start Spark Job)"):
            st.warning("⚠️ Ingestion Pipeline not yet linked to Spark. (Coming in Phase 2)")

    st.divider()
    st.subheader("📚 Current Knowledge Base")
    # Placeholder for file list
    st.write("No documents found in Vector Store.")

# === TAB 3: LEGAL ANALYSIS ===
with tab3:
    st.header("🧠 Intelligent Case Analysis")
    
    # Chat Interface Layout
    messages = st.container(height=400)
    
    # Fake history for UI demo
    with messages:
        st.chat_message("assistant").write("Hello. I am the Fortress AI. I have access to the secure cluster. How can I help with the case files?")

    prompt = st.chat_input("Ask about the documents...")
    
    if prompt:
        with messages:
            st.chat_message("user").write(prompt)
            st.chat_message("assistant").write("⚠️ I cannot answer yet because the **Document Vault** is empty. Please upload files in Tab 2.")
            
