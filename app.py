import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
import time
# --- UPDATED IMPORTS FOR NEW LANGCHAIN VERSION ---
from langchain_community.document_loaders import PyPDFLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tempfile
import os

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal v6.1",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Initialize the AI Brain (Embeddings)
    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    
    DB_STATUS = "🟢 Online"
except Exception as e:
    DB_STATUS = f"🔴 Offline: {e}"
    st.error("Missing Secrets! Check SUPABASE_URL, SUPABASE_KEY, and OPENAI_API_KEY.")
    st.stop()

# --- 2. HELPER FUNCTIONS ---
def get_system_health():
    """Fetch live telemetry."""
    try:
        response = supabase.table("system_health").select("*").order("last_updated", desc=True).limit(20).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['last_updated'] = pd.to_datetime(df['last_updated'])
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def process_and_upload_pdf(uploaded_file):
    """Reads PDF, splits it, creates vectors, and saves to Supabase."""
    try:
        # 1. Save to a temporary file (so PyPDF can read it)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        # 2. Load PDF
        loader = PyPDFLoader(tmp_path)
        docs = loader.load()

        # 3. Split Text into Chunks (1000 characters each)
        # FIXED: Using the new library path
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)

        # 4. Create Vectors & Upload
        # We loop through chunks and upload them one by one
        progress_bar = st.progress(0, text="Vectorizing Document...")
        
        for i, split in enumerate(splits):
            # Generate Vector (The "Math")
            vector = embeddings.embed_query(split.page_content)
            
            # Prepare Data Payload
            data = {
                "content": split.page_content,
                "metadata": {"source": uploaded_file.name, "page": split.metadata.get("page", 0)},
                "embedding": vector
            }
            
            # Save to Database
            supabase.table("documents").insert(data).execute()
            
            # Update Progress
            progress = (i + 1) / len(splits)
            progress_bar.progress(progress, text=f"Processing chunk {i+1}/{len(splits)}")

        # Cleanup
        os.remove(tmp_path)
        return True, len(splits)

    except Exception as e:
        return False, str(e)

# --- 3. MAIN UI ---
st.title("🛡️ Fortress Legal: Enterprise Cluster")
tab1, tab2, tab3 = st.tabs(["📊 Live Telemetry", "📂 Document Vault", "🧠 Legal Analysis"])

# === TAB 1: HARDWARE ===
with tab1:
    if st.button("🔄 Refresh Signal"): st.rerun()
    raw_df = get_system_health()
    if not raw_df.empty:
        snapshot = raw_df.sort_values(by="last_updated", ascending=False).drop_duplicates(subset=["node_id"], keep="first")
        cols = st.columns(len(snapshot))
        for index, (i, row) in enumerate(snapshot.iterrows()):
            with cols[index % len(cols)]:
                with st.expander(f"{'⚓' if '2' in row['node_id'] else '🔥'} {row['node_id']}", expanded=True):
                    st.metric("Temp", f"{row['gpu_temp']}°C")
                    st.metric
