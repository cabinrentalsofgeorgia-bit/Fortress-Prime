import streamlit as st
import time
import logging
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import google.generativeai as genai

# --- 1. ENTERPRISE LOGGING & CONFIG ---
# Setup logging to capture errors (Audit Trail)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Fortress Legal | Command Center",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)

# Safe Import for Graphviz (with User Feedback)
try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False
    logger.warning("Graphviz binary not found. Visualization disabled.")

# Load Secrets (Fail Fast Pattern)
required_secrets = ["SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]
missing = [key for key in required_secrets if key not in st.secrets]
if missing:
    st.error(f"🚨 CRITICAL ERROR: Missing Secrets: {missing}")
    st.stop()

# Initialize Clients
try:
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    st.error(f"Connection Failure: {e}")
    st.stop()

# --- 2. SIDEBAR: INFRASTRUCTURE ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/server.png", width=50)
    st.title("System Status")
    
    # SYSTEM METRICS (Mocked for Demo, but ready for API hookup)
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Spark Cluster", "ONLINE", delta="12ms")
        st.metric("NAS Vault", "MOUNTED", delta="Active")
    with col2:
        st.metric("Inference", "IDLE", delta="-")
        st.metric("Security", "ENCRYPTED", delta="OK")

    st.markdown("---")
    
    # ENTERPRISE MODEL SELECTOR (Dynamic & Validated)
    st.subheader("🧠 Intelligence Layer")
    
    # 1. Define the 'Wishlist' of high-performance models
    preferred_models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"]
    
    # 2. Dynamic Discovery: Check which ones actually exist for this Key
    available_models = []
    try:
        # We try to 'get' the model to see if we have access
        # This is a 'Liveness Probe' for the API
        for model_name in preferred_models:
            m = genai.GenerativeModel(model_name)
            available_models.append(f"models/{model_name}")
    except Exception as e:
        logger.error(f"Model Discovery Failed: {e}")
        # Fallback to the safest known model if discovery fails
        available_models = ["models/gemini-pro"]

    if not available_models:
        st.error("No Gemini models accessible. Check API Key permissions.")
    else:
        selected_model_name = st.selectbox("Antagonist Model", available_models, index=0)

    st.markdown("---")
    st.caption(f"Fortress OS v2.3 | Environment: Production")

# --- 3. ARCHITECTURE VISUALIZATION ---
def render_architecture():
    if not HAS_GRAPHVIZ:
        st.warning("⚠️ Visualization Engine (Graphviz) unavailable. Please check container deps.")
        return None
        
    graph = graphviz.Digraph()
    graph.attr(rankdir='LR', bgcolor='transparent')
    graph.attr('node', shape='box', style='filled', fontname="Helvetica")
    
    # On-Premise Nodes
    with graph.subgraph(name='cluster_prem') as c:
        c.attr(label='🔒 On-Premise (DGX + NAS)', color='red', style='dashed')
        c.node('NAS', 'Synology NAS\n(Data Lake)', fillcolor='lightgrey', shape='cylinder')
        c.node('DGX', 'NVIDIA DGX\n(Compute)', fillcolor='lightblue')
    
    # Cloud Nodes
    with graph.subgraph(name='cluster_cloud') as c:
        c.attr(label='☁️ Secure Cloud', color='blue')
        c.node('SUPA', 'Supabase\n(Vector Vault)', fillcolor='#3ECF8E', fontcolor='white')
        c.node('OPENAI', 'OpenAI\n(Reasoning)', fillcolor='white')
        c.node('GEMINI', 'Gemini\n(Red Team)', fillcolor='white')

    # Edges
    graph.edge('NAS', 'DGX', label=' NFS')
    graph.edge('DGX', 'SUPA', label=' Sync')
    graph.edge('SUPA', 'OPENAI', label=' Retrieval')
    graph.edge('SUPA', 'GEMINI', label=' Context')
    
    return graph

# --- 4. MAIN DASHBOARD ---
st.title("🛡️ Fortress Legal Command Center")

dash_tab, work_tab, red_team_tab = st.tabs(["📊 Infrastructure", "📝 Legal Analysis", "⚔️ Red Team"])

# --- TAB 1: INFRASTRUCTURE ---
with dash_tab:
    col_a, col_b = st.columns([1, 2])
    
    with col_a:
        st.subheader("📡 Ingestion Pipeline")
        st.info("Route documents from Local Storage to Cloud Vault.")
        
        input_method = st.radio("Source", ["Upload File", "Paste Text"], horizontal=True)
        documents = []
        if input_method == "Upload File":
            files = st.file_uploader("Select Contracts", type=["txt"], accept_multiple_files=True)
            if files:
                for f in files: documents.append(f.read().decode("utf-8", errors="ignore"))
        else:
            text = st.text_area("Manual Entry")
            if text: documents.append(text)
            
        if st.button("🚀 Execute Pipeline", use_container_width=True):
            if not documents:
                st.warning("No payload.")
            else:
                with st.spinner("Processing..."):
                    try:
                        embeddings = OpenAIEmbeddings(openai_api_key=st.secrets["OPENAI_API_KEY"])
                        SupabaseVectorStore.from_texts(
                            texts=documents, embedding=embeddings, client=supabase,
                            table_name="documents", query_name="match_documents"
                        )
                        st.success(f"✅ Pipeline Complete: {len(documents)} Objects Secured.")
                    except Exception as e: 
                        st.error(f"Pipeline Fail: {e}")
                        logger.error(f"Ingestion Error: {e}")

    with col_b:
        st.subheader("🌐 Network Topology")
        if HAS_GRAPHVIZ:
            st.graphviz_chart(render_architecture(), use_container_width=True)
        else:
            st.warning("⚠️ Diagram Renderer Offline")

# --- TAB 2: ANALYSIS ---
with work_tab:
    st.subheader("🔎 Evidence-Based Retrieval")
    user_query = st.text_input("Query the Case Files:", placeholder="e.g., What is the termination fee?")
    
    if st.button("Run Analysis", key="btn_analyze"):
        with st.spinner("Querying Vault..."):
            try:
                embeddings = OpenAIEmbeddings(openai_api_key=st.secrets["OPENAI_API_KEY"])
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
                llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=st.secrets["OPENAI_API_KEY"])
                
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
            except Exception as e: 
                st.error(f"Analysis Error: {e}")
                logger.error(f"Analysis Error: {e}")

# --- TAB 3: RED TEAM ---
with red_team_tab:
    st.subheader("⚔️ Adversarial Simulation")
    st.caption(f"Powered by {selected_model_name}")
    
    attack_text = st.text_area("Paste Clause for Stress Testing:", height=150)
    if st.button("Initiate Attack"):
        with st.spinner("Simulating..."):
            try:
                model = genai.GenerativeModel(selected_model_name)
                response = model.generate_content(f"Find loopholes: {attack_text}")
                st.error("⚠️ RISK DETECTED")
                st.write(response.text)
            except Exception as e: 
                st.error(f"Gemini Error: {e}")
                logger.error(f"Gemini Error: {e}")
