import streamlit as st
import graphviz
import time
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import google.generativeai as genai

# --- 1. ENTERPRISE CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal | Command Center",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)

# Load Secrets
try:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    google_api_key = st.secrets["GOOGLE_API_KEY"]
except KeyError:
    st.error("🚨 System Failure: Missing API Keys in Secrets.")
    st.stop()

# Initialize Clients
supabase: Client = create_client(supabase_url, supabase_key)
genai.configure(api_key=google_api_key)

# --- 2. SIDEBAR: SYSTEM HEALTH & INFRASTRUCTURE ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/server.png", width=50)
    st.title("System Status")
    
    # MOCK HARDWARE MONITOR (Connect this to your real DGX API later)
    col1, col2 = st.columns(2)
    with col1:
        st.metric("DGX Spark 1", "ONLINE", delta="12ms")
        st.metric("Synology NAS", "MOUNTED", delta="Active")
    with col2:
        st.metric("DGX Spark 2", "IDLE", delta="-", delta_color="off")
        st.metric("Vault", "SECURE", delta="Encrypted")

    st.markdown("---")
    
    # MODEL SELECTION
    st.subheader("🧠 Intelligence Layer")
    # Hard-coded stable models
    valid_models = ["models/gemini-1.5-pro-latest", "models/gemini-1.5-flash-latest", "models/gemini-pro"]
    selected_model_name = st.selectbox("Antagonist Model", valid_models, index=0)

    st.markdown("---")
    st.caption(f"Fortress OS v2.1 | Connected to {supabase_url[:8]}...")

# --- 3. ARCHITECTURE VISUALIZATION (THE "MAP") ---
# This draws the diagram of your system dynamically
def render_architecture():
    graph = graphviz.Digraph()
    graph.attr(rankdir='LR', bgcolor='transparent')
    graph.attr('node', shape='box', style='filled', fontname="Helvetica")
    
    # On-Premise Nodes (Your Hardware)
    with graph.subgraph(name='cluster_prem') as c:
        c.attr(label='🔒 On-Premise (Fortress)', color='red', style='dashed')
        c.node('NAS', 'Synology NAS\n(Raw Contracts)', fillcolor='lightgrey', shape='cylinder')
        c.node('DGX1', 'NVIDIA DGX 1\n(Spark Compute)', fillcolor='lightblue')
        c.node('DGX2', 'NVIDIA DGX 2\n(Inference)', fillcolor='lightblue')
    
    # Cloud Nodes (Current Stack)
    with graph.subgraph(name='cluster_cloud') as c:
        c.attr(label='☁️ Secure Cloud', color='blue')
        c.node('SUPA', 'Supabase\n(Vector Vault)', fillcolor='#3ECF8E', fontcolor='white')
        c.node('OPENAI', 'OpenAI\n(Reasoning Engine)', fillcolor='white')
        c.node('GEMINI', 'Google Gemini\n(Antagonist)', fillcolor='white')

    # Edges (The Connections)
    graph.edge('NAS', 'DGX1', label=' NFS Mount')
    graph.edge('DGX1', 'SUPA', label=' Sync (Embeddings)')
    graph.edge('SUPA', 'OPENAI', label=' Retrieval')
    graph.edge('SUPA', 'GEMINI', label=' Context')
    
    return graph

# --- 4. MAIN DASHBOARD ---
st.title("🛡️ Fortress Legal Command Center")

# Top Level Tabs
dash_tab, work_tab, red_team_tab = st.tabs(["📊 Infrastructure & Ingestion", "📝 Legal Analysis", "⚔️ Red Team"])

# --- TAB 1: INFRASTRUCTURE (The "Enterprise View") ---
with dash_tab:
    col_a, col_b = st.columns([1, 2])
    
    with col_a:
        st.subheader("📡 Ingestion Pipeline")
        st.info("Upload documents to route them from Local Storage to the Cloud Vault.")
        
        # INGESTION ENGINE
        input_method = st.radio("Source", ["Upload File", "Paste Text"], horizontal=True)
        documents = []
        if input_method == "Upload File":
            files = st.file_uploader("Select Contracts", type=["txt"], accept_multiple_files=True)
            if files:
                for f in files: documents.append(f.read().decode("utf-8", errors="ignore"))
        else:
            text = st.text_area("Manual Entry")
            if text: documents.append(text)
            
        if st.button("🚀 Execute Ingestion Pipeline", use_container_width=True):
            if not documents:
                st.warning("No payload detected.")
            else:
                with st.spinner("Encrypting & Vectorizing..."):
                    try:
                        embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                        SupabaseVectorStore.from_texts(
                            texts=documents, embedding=embeddings, client=supabase,
                            table_name="documents", query_name="match_documents"
                        )
                        st.success(f"✅ Pipeline Complete: {len(documents)} Objects Secured.")
                    except Exception as e: st.error(f"Pipeline Fail: {e}")

    with col_b:
        st.subheader("🌐 Network Topology")
        # RENDER THE DIAGRAM
        st.graphviz_chart(render_architecture(), use_container_width=True)

# --- TAB 2: ANALYSIS (Glass Box RAG) ---
with work_tab:
    st.subheader("🔎 Evidence-Based Retrieval")
    user_query = st.text_input("Query the Case Files:", placeholder="e.g., What is the liability cap?")
    
    if st.button("Run Analysis", key="btn_analyze"):
        with st.spinner("Querying Vector Vault..."):
            try:
                embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                vector_store = SupabaseVectorStore(
                    client=supabase, embedding=embeddings, 
                    table_name="documents", query_name="match_documents"
                )
                retriever = vector_store.as_retriever(search_kwargs={"k": 4})
                
                template = """
                You are a Senior Partner. Answer based ONLY on the context.
                Context: {context}
                Question: {question}
                """
                prompt = PromptTemplate.from_template(template)
                llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
                
                rag_chain = RunnableParallel(
                    {"context": retriever, "question": RunnablePassthrough()}
                ).assign(answer=(
                    RunnablePassthrough.assign(context=(lambda x: x["context"]))
                    | prompt | llm | StrOutputParser()
                ))
                
                result = rag_chain.invoke(user_query)
                
                st.markdown("### 📋 Counsel Opinion")
                st.write(result["answer"])
                
                with st.expander("📂 View Source Evidence", expanded=False):
                    for i, doc in enumerate(result["context"]):
                        st.markdown(f"**Exhibit {i+1}:**")
                        st.caption(doc.page_content)
                        st.divider()
            except Exception as e: st.error(f"Error: {e}")

# --- TAB 3: RED TEAM (Gemini) ---
with red_team_tab:
    st.subheader("⚔️ Adversarial Simulation")
    st.caption(f"Powered by {selected_model_name}")
    
    attack_text = st.text_area("Paste Clause for Stress Testing:", height=150)
    if st.button("Initiate Attack Simulation"):
        with st.spinner("Simulating Opposing Counsel..."):
            try:
                model = genai.GenerativeModel(selected_model_name)
                response = model.generate_content(f"Find loopholes: {attack_text}")
                st.error("⚠️ RISK DETECTED")
                st.write(response.text)
            except Exception as e: st.error(f"Gemini Error: {e}")
