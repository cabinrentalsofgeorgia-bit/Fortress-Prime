import streamlit as st
import pandas as pd
import plotly.express as px
import psycopg2
import os
import tempfile
from pdf2image import convert_from_path
import pytesseract
from datetime import datetime

from prompts.loader import load_prompt

# --- Centralized Cluster Config ---
from config import (
    CAPTAIN_MODEL,
    MUSCLE_NODE, MUSCLE_VISION_MODEL, MUSCLE_GENERATE_URL,
    MUSCLE_EMBED_MODEL, MUSCLE_IP, WORKER_IP,
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    muscle_see, muscle_embed, captain_think,
)

# --- 1. ENTERPRISE CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Prime (Sovereign)",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Cluster endpoints (derived from config.py)
DB_PASS = DB_PASSWORD
CHAT_MODEL = CAPTAIN_MODEL             # DeepSeek-R1
EMBED_MODEL = MUSCLE_EMBED_MODEL       # nomic-embed-text on Spark 1

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
    system_role = load_prompt("captain_senior_analyst").render()
    full_prompt = f"System: {system_role} Use this context:\n{context}\n\nUser: {prompt}\n\nAnswer:"
    try:
        response = captain_think(prompt=full_prompt, system_role="", temperature=0.3)
        return response or "⚠️ Worker Silent."
    except Exception as e:
        return f"🚨 Connection Failure: {e}"

def vectorize_text(text):
    """Ask Worker to convert text to math."""
    try:
        return muscle_embed(text)
    except Exception:
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

# --- 4. FINANCIALS (Live CFO Audit CSV) ---
CFO_CSV_PATH = "/mnt/fortress_nas/fortress_data/ai_brain/logs/cfo_extractor/financial_audit.csv"

def get_financial_audit_df():
    """Load live CFO extraction CSV; return (df, has_errors)."""
    if not os.path.isfile(CFO_CSV_PATH):
        return pd.DataFrame(), False
    try:
        df = pd.read_csv(CFO_CSV_PATH, encoding="utf-8", on_bad_lines="skip")
        if df.empty:
            return df, False
        has_errors = "error" in df.columns and df["error"].fillna("").astype(str).str.len().gt(0).any()
        return df, has_errors
    except Exception:
        return pd.DataFrame(), False

# --- 5. MAIN DASHBOARD ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Intelligence Vault", "🔎 Semantic Search", "💬 Analyst Chat", "💰 Financials"])

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
    st.subheader("Ask Fortress Analyst")
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

with tab4:
    st.subheader("💰 Burn Rate by Category (Live CFO Audit)")
    df_fin, has_errors = get_financial_audit_df()
    if df_fin.empty:
        st.info("No financial audit data yet. CFO batch writes to the CSV as it processes files.")
        st.caption(f"Path: {CFO_CSV_PATH}")
    else:
        # Success vs error counts
        error_col = "error" if "error" in df_fin.columns else None
        if error_col:
            ok = df_fin[df_fin[error_col].fillna("").astype(str).str.len() == 0]
            err_count = len(df_fin) - len(ok)
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Processed", len(df_fin))
            col2.metric("Extracted OK", len(ok))
            col3.metric("Errors / Timeouts", err_count)
            plot_df = ok.copy()
        else:
            plot_df = df_fin.copy()
            st.metric("Rows Processed", len(df_fin))

        # Burn rate by category (only rows with numeric total_amount)
        if "total_amount" in plot_df.columns and "category" in plot_df.columns:
            plot_df["total_amount"] = pd.to_numeric(plot_df["total_amount"], errors="coerce")
            by_cat = plot_df.dropna(subset=["total_amount"]).groupby("category", as_index=False)["total_amount"].sum()
            if not by_cat.empty:
                fig = px.bar(by_cat, x="category", y="total_amount", title="Spend by Category",
                             labels={"total_amount": "Total Amount", "category": "Category"})
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("No amounts extracted yet (or all timeouts).")
        else:
            st.caption("CSV does not have total_amount/category yet.")

        st.subheader("Recent Rows")
        # Show last N rows; hide long error text in display
        display_cols = [c for c in ["filename", "processed_at", "date", "vendor", "total_amount", "category", "tax_deductible", "summary", "error"] if c in df_fin.columns]
        show = df_fin[display_cols].tail(50)
        if "error" in show.columns:
            show["error"] = show["error"].fillna("").astype(str).str[:80]
        st.dataframe(show, use_container_width=True)
        st.caption(f"Live path: {CFO_CSV_PATH}")
