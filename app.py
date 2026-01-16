import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
import time
# --- UPDATED IMPORTS ---
import pypdf
from langchain_core.documents import Document  # <--- FIXED LOCATION
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tempfile
import os

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal v7.2",
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
    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    
except Exception as e:
    st.error(f"❌ Connection Error: {e}")
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
    """Reads PDF carefully, ignores bad pages, splits, and saves."""
    try:
        # 1. Save Temp File
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        # 2. Robust PDF Reading
        text_content = ""
        try:
            reader = pypdf.PdfReader(tmp_path)
            for page in reader.pages:
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n"
                except Exception:
                    continue
        except Exception as e:
            return False, f"PDF Read Error: {e}"

        if not text_content:
            return False, "No readable text found in PDF (Is it a scanned image?)"

        # 3. Create Document Object
        raw_doc = Document(page_content=text_content, metadata={"source": uploaded_file.name})

        # 4. Split Text
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents([raw_doc])

        # 5. Vectorize & Upload
        progress_bar = st.progress(0, text="Vectorizing Document...")
        for i, split in enumerate(splits):
            vector = embeddings.embed_query(split.page_content)
            data = {
                "content": split.page_content,
                "metadata": {"source": uploaded_file.name, "page": i},
                "embedding": vector
            }
            supabase.table("documents").insert(data).execute()
            progress_bar.progress((i + 1) / len(splits))

        os.remove(tmp_path)
        return True, len(splits)

    except Exception as e:
        return False, str(e)

# --- 3. MAIN UI ---
st.title("🛡️ Fortress Legal: Enterprise Cluster")
tab1, tab2, tab3 = st.tabs(["📊 Live Telemetry", "📂 Document Vault", "🧠 Legal Analysis"])

# === TAB 1: HARDWARE ===
with tab1:
    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("🔄 Refresh"): st.rerun()
    
    raw_df = get_system_health()
    if not raw_df.empty:
        snapshot = raw_df.sort_values(by="last_updated", ascending=False).drop_duplicates(subset=["node_id"], keep="first")
        cols = st.columns(len(snapshot))
        for index, (i, row) in enumerate(snapshot.iterrows()):
            with cols[index % len(cols)]:
                with st.container(border=True):
                    icon = "⚓" if "2" in row['node_id'] else "🔥"
                    st.subheader(f"{icon} {row['node_id']}")
                    m1, m2 = st.columns(2)
                    m1.metric("Temp", f"{row['gpu_temp']}°C")
                    m2.metric("VRAM", f"{row['vram_used']} MB")
                    load = int(row['gpu_util']) if pd.notnull(row['gpu_util']) else 0
                    st.progress(load, text=f"GPU Load: {load}%")
                    st.caption(f"Last Pulse: {row['last_updated'].strftime('%H:%M:%S')}")

# === TAB 2: INGESTION ENGINE ===
with tab2:
    st.header("📂 Legal Document Ingestion")
    uploaded_files = st.file_uploader("Upload Case Files (PDF)", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        if st.button(f"🚀 Ingest {len(uploaded_files)} File(s)"):
            for file in uploaded_files:
                st.write(f"Processing **{file.name}**...")
                success, details = process_and_upload_pdf(file)
                if success:
                    st.success(f"✅ Indexed {file.name} ({details} chunks)")
                else:
                    st.error(f"❌ Error: {details}")

# === TAB 3: ANALYSIS ===
with tab3:
    st.header("🧠 Intelligent Case Analysis")
    query = st.text_input("Ask a question about the uploaded files:")
    if st.button("Analyze"):
        st.info("Analysis Engine coming in Phase 3.")
