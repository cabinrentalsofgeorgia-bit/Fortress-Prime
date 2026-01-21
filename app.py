import streamlit as st
import pandas as pd
import plotly.express as px
import psycopg2
import requests
import os
import tempfile
from pdf2image import convert_from_path
import pytesseract
from datetime import datetime

# --- 1. ENTERPRISE CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Prime (Sovereign)",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# The Captain (Local DB)
DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "secure_password"

# The Worker (Remote GPU)
WORKER_IP = "192.168.0.104"
OLLAMA_CHAT = f"http://{WORKER_IP}:11434/api/generate"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
CHAT_MODEL = "llama3.2"
EMBED_MODEL = "nomic-embed-text"

# --- 2. BACKEND FUNCTIONS ---
def get_intel_stats():
    """Check the Vault for intelligence data."""
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        df = pd.read_sql("SELECT id, source_file, created_at FROM market_intel", conn)
        conn.close()
        return df
    except:
        return pd.DataFrame()

def ask_worker(prompt, context=""):
    """Send orders to the GPU Worker."""
    full_prompt = f"System: You are a Senior Analyst. Use this context:\n{context}\n\nUser: {prompt}\n\nAnswer:"
    try:
        resp = requests.post(OLLAMA_CHAT, json={"model": CHAT_MODEL, "prompt": full_prompt, "stream": False}, timeout=90)
        return resp.json().get('response', "⚠️ Worker Silent.")
    except Exception as e:
        return f"🚨 Connection Failure: {e}"

def vectorize_text(text):
    """Ask Worker to convert text to math."""
    try:
        resp = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": text}, timeout=10)
        return resp.json()['embedding']
    except:
        return None

# --- 3. SIDEBAR: INGESTION ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/fortress.png", width=60)
    st.header("Fortress Prime")
    st.info(f"⚡ GPU Link: {WORKER_IP}")
    
    st.subheader("📥 Upload Intel")
    uploaded_file = st.file_uploader("Drop PDF Reports", type="pdf")
    
    if uploaded_file and st.button("Process & Index"):
        with st.spinner("The Captain is reading..."):
            # Save Temp
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.getbuffer())
                tmp_path = tmp.name
            
            # OCR (Vision)
            images = convert_from_path(tmp_path)
            text = "".join([pytesseract.image_to_string(img) for img in images])
            os.remove(tmp_path)
            
            # Chunk & Embed
            chunks = [text[i:i+800] for i in range(0, len(text), 800)]
            conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
            cur = conn.cursor()
            
            progress = st.progress(0)
            for i, chunk in enumerate(chunks):
                if len(chunk) < 50: continue
                vec = vectorize_text(chunk)
                if vec:
                    cur.execute("INSERT INTO market_intel (source_file, chunk_index, content, embedding) VALUES (%s, %s, %s, %s)",
                                (uploaded_file.name, i, chunk, vec))
                progress.progress((i+1)/len(chunks))
            
            conn.commit()
            conn.close()
            st.success(f"Indexed {len(chunks)} Blocks!")
            st.rerun()

# --- 4. MAIN DASHBOARD ---
tab1, tab2, tab3 = st.tabs(["📊 Intelligence Vault", "🔎 Semantic Search", "💬 Analyst Chat"])

with tab1:
    st.subheader("Vault Status")
    df = get_intel_stats()
    if not df.empty:
        col1, col2 = st.columns(2)
        col1.metric("Total Documents", df['source_file'].nunique())
        col2.metric("Knowledge Blocks", len(df))
        
        st.dataframe(df.sort_values("created_at", ascending=False), use_container_width=True)
    else:
        st.warning("The Vault is empty. Upload a PDF in the sidebar.")

with tab2:
    st.subheader("Deep Search")
    query = st.text_input("Search the database:", placeholder="e.g. 'Consensus on inflation'")
    if query:
        vec = vectorize_text(query)
        if vec:
            conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
            cur = conn.cursor()
            cur.execute("SELECT content, source_file FROM market_intel ORDER BY embedding <=> %s::vector LIMIT 4", (str(vec),))
            results = cur.fetchall()
            conn.close()
            
            for r in results:
                with st.expander(f"📄 Source: {r[1]}"):
                    st.write(r[0])

with tab3:
    st.subheader("Ask Llama 3.2")
    user_q = st.chat_input("Ask the Analyst...")
    
    if "history" not in st.session_state:
        st.session_state.history = []

    # Display History
    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if user_q:
        # Show User Message
        with st.chat_message("user"):
            st.write(user_q)
        st.session_state.history.append({"role": "user", "content": user_q})
        
        # RAG Retrieval
        vec = vectorize_text(user_q)
        context_str = ""
        if vec:
            conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
            cur = conn.cursor()
            cur.execute("SELECT content FROM market_intel ORDER BY embedding <=> %s::vector LIMIT 5", (str(vec),))
            rows = cur.fetchall()
            conn.close()
            context_str = "\n".join([r[0] for r in rows])
        
        # Generate Answer
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                ans = ask_worker(user_q, context=context_str)
                st.write(ans)
        st.session_state.history.append({"role": "assistant", "content": ans})
