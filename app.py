import streamlit as st
import time
import datetime
import pandas as pd
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import google.generativeai as genai

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal | DGX Command Center",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)

# Safe Graphviz
try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False

# Load Secrets
try:
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    st.error(f"System Offline: {e}")
    st.stop()

# --- 2. LIVE TELEMETRY FETCHER ---
def get_hardware_stats():
    """Fetches real-time GPU/CPU stats from Supabase."""
    try:
        # Sort by last_updated to get the absolute latest heartbeat
        response = supabase.table("system_health").select("*").execute()
        # Convert to dictionary keyed by Node ID
        stats = {row['node_id']: row for row in response.data}
        return stats
    except:
        return {}

def check_ingestion_status():
    """Checks if documents are being added."""
    try:
        res = supabase.table("documents").select("created_at", count="exact").order("created_at", desc=True).limit(1).execute()
        total = res.count if res.count else 0
        last_time = res.data[0]['created_at'] if res.data else None
        
        status = "IDLE"
        if last_time:
            last_active = datetime.datetime.fromisoformat(last_time.replace('Z', '+00:00'))
            delta = (datetime.datetime.now(datetime.timezone.utc) - last_active).total_seconds()
            if delta < 120: status = "INGESTING"
            
        return total, status
    except:
        return 0, "OFFLINE"

# Fetch Data
hw_stats = get_hardware_stats()
doc_count, sys_status = check_ingestion_status()

# --- 3. SIDEBAR: NETOPS VIEW ---
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/server.png", width=60)
    st.title("NetOps Command")
    
    # REFRESHER
    if st.button("🔄 Refresh Telemetry"):
        st.rerun()

    st.markdown("---")
    st.subheader("🟢 Cluster Health")

    # SPARK 1 MONITOR
    s1 = hw_stats.get("Spark-1", {})
    with st.expander("🔥 Spark 1 (DGX Worker)", expanded=True):
        if s1:
            st.caption(f"Last Heartbeat: {s1.get('last_updated', 'Unknown')}")
            colA, colB = st.columns(2)
            colA.metric("GPU Temp", f"{s1.get('gpu_temp',0)}°C", f"{s1.get('gpu_util',0)}% Load")
            colB.metric("VRAM", f"{s1.get('vram_used',0)}MB", "Allocated")
            st.progress(min(s1.get('cpu_usage', 0), 100) / 100, text=f"CPU Load: {s1.get('cpu_usage',0)}%")
            st.progress(min(s1.get('ram_usage', 0), 100) / 100, text=f"RAM Usage: {s1.get('ram_usage',0)}%")
        else:
            st.warning("Signal Lost - Check Script")

    # SPARK 2 MONITOR
    s2 = hw_stats.get("Spark-2", {})
    with st.expander("⚓ Spark 2 (DGX Captain)", expanded=True):
        if s2:
            st.caption(f"Last Heartbeat: {s2.get('last_updated', 'Unknown')}")
            colA, colB = st.columns(2)
            colA.metric("GPU Temp", f"{s2.get('gpu_temp',0)}°C", f"{s2.get('gpu_util',0)}% Load")
            colB.metric("VRAM", f"{s2.get('vram_used',0)}MB", "Allocated")
            st.progress(min(s2.get('cpu_usage', 0), 100) / 100, text=f"CPU Load: {s2.get('cpu_usage',0)}%")
            st.progress(min(s2.get('ram_usage', 0), 100) / 100, text=f"RAM Usage: {s2.get('ram_usage',0)}%")
        else:
            st.warning("Signal Lost - Check Script")

    st.markdown("---")
    # MODEL SELECTOR
    valid_models = ["models/gemini-1.5-pro", "models/gemini-1.5-flash", "models/gemini-pro"]
    selected_model_name = st.selectbox("Intelligence Model", valid_models, index=0)

# --- 4. ARCHITECTURE MAP ---
def render_map():
    if not HAS_GRAPHVIZ: return None
    graph = graphviz.Digraph()
    graph.attr(rankdir='LR', bgcolor='transparent')
    graph.attr('node', shape='box', style='filled', fontname="Helvetica")
    
    # ON-PREM
    with graph.subgraph(name='cluster_prem') as c:
        c.attr(label='🏢 On-Premise DGX Cluster', color='red', style='dashed')
        c.node('NAS', 'Synology NAS\n(Data Lake)', shape='cylinder', fillcolor='lightgrey')
        
        # Dynamic Coloring based on Load
        s1_load = hw_stats.get("Spark-1", {}).get('gpu_util', 0)
        s2_load = hw_stats.get("Spark-2", {}).get('gpu_util', 0)
        
        # Color Logic: Green if reporting (temp >= 0), Red if hot, White if missing
        color1 = '#ffcccb' if s1_load > 80 else ('#90EE90' if "Spark-1" in hw_stats else 'white')
        color2 = '#ffcccb' if s2_load > 80 else ('#90EE90' if "Spark-2" in hw_stats else 'white')

        c.node('SPK1', f'Spark 1\n(CPU: {hw_stats.get("Spark-1", {}).get("cpu_usage", "?")}%)', fillcolor=color1)
        c.node('SPK2', f'Spark 2\n(CPU: {hw_stats.get("Spark-2", {}).get("cpu_usage", "?")}%)', fillcolor=color2)

    # CLOUD
    with graph.subgraph(name='cluster_cloud') as c:
        c.attr(label='☁️ Cloud', color='blue')
        c.node('DB', f'Supabase\n({doc_count} Docs)', fillcolor='#3ECF8E')
        c.node('AI', 'OpenAI + Gemini', fillcolor='white')

    graph.edge('NAS', 'SPK1'); graph.edge('NAS', 'SPK2')
    graph.edge('SPK1', 'DB'); graph.edge('SPK2', 'DB')
    graph.edge('DB', 'AI')
    return graph

# --- 5. MAIN TABS ---
st.title("🛡️ Fortress Legal Command Center")
tab1, tab2, tab3 = st.tabs(["📊 Live Infrastructure", "📝 Legal Analysis", "⚔️ Red Team"])

with tab1:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("📡 Ingestion Status")
        if sys_status == "INGESTING":
            st.success(f"⚡ Cluster is Active. Ingesting Data.")
        else:
            st.info("💤 Cluster is Idle.")
        
        st.metric("Total Documents Secured", f"{doc_count:,}")
        
    with col2:
        st.subheader("🌐 Hardware Topology")
        if HAS_GRAPHVIZ: st.graphviz_chart(render_map(), use_container_width=True)

with tab2:
    query = st.text_input("Query Case Files:")
    if st.button("Analyze"):
        with st.spinner("Analyzing..."):
            try:
                embeddings = OpenAIEmbeddings(openai_api_key=st.secrets["OPENAI_API_KEY"])
                vector_store = SupabaseVectorStore(client=supabase, embedding=embeddings, table_name="documents", query_name="match_documents")
                retriever = vector_store.as_retriever(search_kwargs={"k": 4})
                llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=st.secrets["OPENAI_API_KEY"])
                rag_chain = RunnableParallel({"context": retriever, "question": RunnablePassthrough()}).assign(answer=(RunnablePassthrough.assign(context=(lambda x: x["context"])) | PromptTemplate.from_template("Answer based on context:\n{context}\nQ:{question}") | llm | StrOutputParser()))
                res = rag_chain.invoke(query)
                st.write(res["answer"])
                with st.expander("Evidence"):
                    for doc in res["context"]: st.info(doc.page_content)
            except Exception as e: st.error(f"Error: {e}")

with tab3:
    attack = st.text_area("Clause to Attack:")
    if st.button("Simulate"):
        try:
            model = genai.GenerativeModel(selected_model_name)
            st.write(model.generate_content(f"Destroy: {attack}").text)
        except Exception as e: st.error(f"Error: {e}")
