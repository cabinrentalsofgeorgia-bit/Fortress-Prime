import streamlit as st
import chromadb
import os
import shutil
import time
import json
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings

MASTER_DB_DIR = "/mnt/ai-data/chroma_db"
SNAPSHOT_DIR = "/tmp/chroma_snapshot_read_only"
STATUS_FILE = "/mnt/ai-data/ingestion_status.json"

st.set_page_config(page_title="Fortress Mission Control", layout="wide", page_icon="🏰")
st.title("🏰 Fortress Command Center")

# --- SIDEBAR (THE MONITOR) ---
with st.sidebar:
    st.header("📡 Live Telemetry")
    
    # Check Spark 2 Status
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r") as f:
                stats = json.load(f)
            
            if stats.get("status") == "active":
                st.info("🟢 Spark 2: INGESTING")
                
                # Progress Bar
                current = stats.get("files_processed", 0)
                total = stats.get("total_files_estimated", 1000)
                if total == 0: total = 1
                progress = min(current / total, 1.0)
                
                st.progress(progress)
                st.caption(f"{current} / {total} Files")
                st.text(f"Scanning: {stats.get('current_file', '...')[:20]}...")
            elif stats.get("status") == "complete":
                st.success("✅ Ingestion Complete")
        except:
            st.warning("⚠️ Telemetry Signal Weak")
    else:
        st.error("🔴 Spark 2: OFFLINE")

    st.divider()
    
    # Snapshot Controls
    st.header("🧠 Knowledge Base")
    if st.button("🔄 Sync with Master Brain"):
        if os.path.exists(SNAPSHOT_DIR): shutil.rmtree(SNAPSHOT_DIR)
        try:
            shutil.copytree(MASTER_DB_DIR, SNAPSHOT_DIR, ignore=shutil.ignore_patterns('*.lock'))
            st.success("Synced!")
            time.sleep(1)
            st.rerun()
        except:
            st.error("Sync Failed")

# --- MAIN APP ---
@st.cache_resource
def load_db():
    if not os.path.exists(SNAPSHOT_DIR):
        return None
    try:
        embedding_function = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
        db = Chroma(persist_directory=SNAPSHOT_DIR, embedding_function=embedding_function)
        return db
    except:
        return None

db = load_db()

query = st.text_input("Query the Archive:", placeholder="Search legal docs...")

if query:
    if db:
        results = db.similarity_search(query, k=4)
        st.write("### 🔍 Search Results")
        for i, doc in enumerate(results):
            source = os.path.basename(doc.metadata.get('source', 'Unknown'))
            with st.expander(f"📄 {source}"):
                st.info(doc.page_content)
    else:
        st.warning("⚠️ Brain not loaded. Click 'Sync' in the sidebar.")
