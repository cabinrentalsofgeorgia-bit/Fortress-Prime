import streamlit as st
import psycopg2
import requests
import json
import time
import random
import os

# --- CLUSTER CONFIGURATION ---
CLUSTER_NODES = {
    "Spark-1 (Primary)": {"ip": "192.168.0.104", "role": "Vector Store"},
    "Spark-2 (Inference)": {"ip": "192.168.0.105", "role": "LLM Engine"}
}

DB_PASS = "190AntiochCemeteryRD!!!"
OLLAMA_API_URL = "http://192.168.0.104:11434/api"

# --- UI CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal: Enterprise Cluster", 
    page_icon="🛡️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Enterprise CSS Theme
st.markdown("""
<style>
    .stApp { background-color: #0f1116; color: #e0e0e0; }
    [data-testid="stSidebar"] { background-color: #15171e; border-right: 1px solid #333; }
    
    .metric-card {
        background-color: #1f2937;
        padding: 10px;
        border-radius: 5px;
        border-left: 4px solid #d4af37;
        margin-bottom: 10px;
    }
    .node-title { font-size: 0.9em; font-weight: bold; color: #fff; }
    .node-stat { font-size: 0.8em; color: #aaa; }
    .stat-value { color: #4ade80; font-weight: bold; }
    .danger { color: #f87171; }
    
    h1, h2, h3 { color: #d4af37; font-family: 'Helvetica Neue', sans-serif; font-weight: 300; }
    .stButton > button { background-color: #d4af37; color: black; font-weight: bold; border: none; }
</style>
""", unsafe_allow_html=True)

# --- BACKEND FUNCTIONS ---

def get_node_status(ip):
    try:
        response = requests.get(f"http://{ip}:11434", timeout=1)
        return response.status_code == 200
    except:
        return False

def get_embedding(text):
    try:
        response = requests.post(f"{OLLAMA_API_URL}/embeddings", json={"model": "nomic-embed-text", "prompt": text}, timeout=5)
        if response.status_code == 200: return response.json().get("embedding")
    except: return None
    return None

def search_memory(query, limit=5):
    vector = get_embedding(query)
    if not vector: return []
    try:
        conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)
        cur = conn.cursor()
        cur.execute("""
            SELECT content, subject_line, 1 - (embedding <=> %s::vector) as similarity
            FROM market_intel
            WHERE 1 - (embedding <=> %s::vector) > 0.45
            ORDER BY similarity DESC LIMIT %s
        """, (vector, limit))
        results = cur.fetchall()
        conn.close()
        return results
    except: return []

def stream_ai_response(prompt, context):
    system_prompt = f"You are Fortress Legal AI. Answer using this context:\n{context}\n\nQuery: {prompt}"
    payload = {"model": "mistral", "prompt": system_prompt, "stream": True}
    try:
        with requests.post(f"{OLLAMA_API_URL}/generate", json=payload, stream=True, timeout=300) as r:
            for line in r.iter_lines():
                if line:
                    body = json.loads(line)
                    if "response" in body: yield body["response"]
    except Exception as e:
        yield f"[Connection Error]: {e}"

# --- SIDEBAR: LIVE TELEMETRY ---
with st.sidebar:
    st.image("https://img.icons8.com/ios-filled/100/d4af37/server.png", width=60)
    st.title("FORTRESS LEGAL")
    st.caption("Enterprise Cluster Status")
    
    st.markdown("### 📊 Live Telemetry")
    
    for name, config in CLUSTER_NODES.items():
        is_online = get_node_status(config['ip'])
        status_color = "🟢" if is_online else "🔴"
        
        # Simulating metrics for visualization
        temp = random.randint(60, 75) if is_online else 0
        vram = random.randint(200, 6000) if is_online else 0
        load = random.randint(80, 99) if is_online else 0
        temp_color = "danger" if temp > 70 else "stat-value"
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="node-title">{status_color} {name}</div>
            <div class="node-stat">Role: {config['role']}</div>
            <hr style="margin: 5px 0; border-color: #444;">
            <div class="node-stat">Temp: <span class="{temp_color}">{temp}°C</span></div>
            <div class="node-stat">VRAM: <span class="stat-value">{vram} MB</span></div>
            <div class="node-stat">GPU Load: <span class="stat-value">{load}%</span></div>
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown("---")
    app_mode = st.radio("Module Selection:", ["Legal Analysis", "Document Vault", "System Admin"])

# --- MAIN PAGE ---

if app_mode == "Legal Analysis":
    st.header("🧠 Neural Legal Analysis")
    query = st.text_area("Input Case Context or Legal Query:", height=100)
    
    if st.button("Analyze with Spark Cluster"):
        if query:
            with st.spinner("Broadcasting to Spark-1 & Spark-2..."):
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.subheader("📂 Evidence Retrieval")
                    results = search_memory(query)
                    context_blob = ""
                    
                    if results:
                        for i, (content, title, score) in enumerate(results):
                            with st.expander(f"{title} ({round(score*100)}%)"):
                                st.caption(content[:400] + "...")
                                context_blob += f"SOURCE {i+1} [{title}]:\n{content}\n\n"
                    else:
                        st.warning("No archival matches found. Using base model knowledge.")

                with col2:
                    st.subheader("🤖 Spark-2 Inference")
                    response_box = st.empty()
                    full_resp = ""
                    
                    for chunk in stream_ai_response(query, context_blob):
                        full_resp += chunk
                        response_box.markdown(full_resp + "▌")
                    response_box.markdown(full_resp)

elif app_mode == "Document Vault":
    st.header("🗄️ Document Vault")
    st.markdown("### Upload New Assets")
    
    uploaded_file = st.file_uploader("Upload PDF / Text File", type=["pdf", "txt", "md"])
    
    if uploaded_file:
        if not os.path.exists("./uploads"):
            os.makedirs("./uploads")

        file_path = f"./uploads/{uploaded_file.name}"
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"File saved: {uploaded_file.name}")
        
        if st.button("Ingest into Neural Core"):
            with st.spinner("Vectorizing..."):
                try:
                    text_content = uploaded_file.getvalue().decode("utf-8")
                    vector = get_embedding(text_content)
                    if vector:
                        conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT INTO market_intel (source_file, content, embedding, sender, subject_line, sent_at)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                        """, (uploaded_file.name, text_content, vector, "User Upload", f"[UPLOAD] {uploaded_file.name}"))
                        conn.commit()
                        conn.close()
                        st.success("Ingestion Complete. Asset is now searchable.")
                except Exception as e:
                    st.error(f"Ingestion Failed: {e}")

    st.markdown("---")
    st.subheader("Database Explorer")
    search_term = st.text_input("Filter Records by Keyword:")
    if search_term:
        conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)
        cur = conn.cursor()
        cur.execute("SELECT id, subject_line, sent_at FROM market_intel WHERE content ILIKE %s ORDER BY sent_at DESC LIMIT 10", (f"%{search_term}%",))
        rows = cur.fetchall()
        conn.close()
        st.table(rows)

elif app_mode == "System Admin":
    st.header("⚙️ Cluster Administration")
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Primary Node (Spark-1):** {CLUSTER_NODES['Spark-1 (Primary)']['ip']}")
        if st.button("Ping Spark-1"):
            status = get_node_status(CLUSTER_NODES['Spark-1 (Primary)']['ip'])
            st.write(f"Status: {'🟢 Online' if status else '🔴 Offline'}")
            
    with col2:
        st.info(f"**Inference Node (Spark-2):** {CLUSTER_NODES['Spark-2 (Inference)']['ip']}")
        if st.button("Ping Spark-2"):
            status = get_node_status(CLUSTER_NODES['Spark-2 (Inference)']['ip'])
            st.write(f"Status: {'🟢 Online' if status else '🔴 Offline'}")

    st.markdown("---")
    st.caption("Fortress Legal v2.1 | Enterprise Cluster Edition")
