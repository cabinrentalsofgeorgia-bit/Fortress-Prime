import streamlit as st
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import google.generativeai as genai

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="Fortress Legal (Enterprise)", layout="wide")

try:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    google_api_key = st.secrets["GOOGLE_API_KEY"]
except KeyError:
    st.error("🚨 Missing Secrets! Please check your Streamlit Secrets.")
    st.stop()

# Connect to Supabase
supabase: Client = create_client(supabase_url, supabase_key)

# Configure Gemini (The Antagonist)
genai.configure(api_key=google_api_key)

# --- 2. SIDEBAR: SYNC ENGINE ---
with st.sidebar:
    st.header("🗄️ Case Files")
    st.caption("Syncs to Supabase (Cloud Vault)")
    
    input_method = st.radio("Input Method", ["Upload Text File", "Paste Text"])
    documents = []
    
    if input_method == "Upload Text File":
        files = st.file_uploader("Upload Contracts (.txt)", type=["txt"], accept_multiple_files=True)
        if files:
            for f in files: documents.append(f.read().decode("utf-8", errors="ignore"))
    elif input_method == "Paste Text":
        text = st.text_area("Paste text here")
        if text: documents.append(text)

    if st.button("Sync to Cloud"):
        if not documents:
            st.warning("No documents found.")
        else:
            with st.spinner("Indexing into Secure Vault..."):
                try:
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    SupabaseVectorStore.from_texts(
                        texts=documents, embedding=embeddings, client=supabase,
                        table_name="documents", query_name="match_documents"
                    )
                    st.success(f"✅ Indexed {len(documents)} documents.")
                except Exception as e: st.error(f"Sync Error: {e}")

# --- 3. MAIN INTERFACE ---
st.title("🛡️ Fortress Legal")
st.caption("Enterprise RAG | GPT-4o (Defense) vs Gemini 1.5 Pro (Prosecution)")

tab1, tab2 = st.tabs(["📝 Evidence-Based Analysis", "⚖️ The Antagonist"])

# --- TAB 1: DEFENSE (GPT-4o) ---
with tab1:
    user_query = st.text_area("Ask a legal question (Citations Enabled):", height=100)
    
    if st.button("Run Legal Analysis"):
        if not user_query:
            st.warning("Enter a query.")
        else:
            with st.spinner("Retrieving Evidence..."):
                try:
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    vector_store = SupabaseVectorStore(
                        client=supabase, embedding=embeddings, 
                        table_name="documents", query_name="match_documents"
                    )
                    retriever = vector_store.as_retriever(search_kwargs={"k": 4})
                    
                    template = """
                    You are a Senior Associate at a top-tier law firm.
                    Answer the question based ONLY on the following context.
                    If the answer is not in the context, explicitly state "I cannot find this in the case files."
                    
                    Context:
                    {context}
                    
                    Question: {question}
                    """
                    prompt = PromptTemplate.from_template(template)
                    llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
                    
                    # Parallel Chain for Transparency
                    rag_chain_from_docs = (
                        RunnablePassthrough.assign(context=(lambda x: x["context"]))
                        | prompt | llm | StrOutputParser()
                    )
                    rag_chain_with_source = RunnableParallel(
                        {"context": retriever, "question": RunnablePassthrough()}
                    ).assign(answer=rag_chain_from_docs)
                    
                    result = rag_chain_with_source.invoke(user_query)
                    
                    st.markdown("### 📋 Memorandum")
                    st.write(result["answer"])
                    
                    st.markdown("---")
                    st.markdown("#### 🔍 Evidence (Source Text)")
                    for i, doc in enumerate(result["context"]):
                        with st.expander(f"Source Snippet #{i+1}"):
                            st.info(doc.page_content)
                except Exception as e: st.error(f"Error: {e}")

# --- TAB 2: PROSECUTION (Gemini 1.5 Pro) ---
with tab2:
    st.info("Gemini 1.5 Pro (Latest) - 'Red Team' Mode")
    text_to_attack = st.text_area("Paste a clause to attack:", height=150)
    
    if st.button("Simulate Opposing Counsel"):
        if not text_to_attack:
            st.warning("Paste a clause first.")
        else:
            with st.spinner("Gemini is dissecting the argument..."):
                try:
                    # FIX: Use the specific latest model name
                    model = genai.GenerativeModel('gemini-1.5-pro-latest')
                    
                    prompt = f"""
                    You are a ruthless opposing counsel.
                    Your goal is to find every loophole, ambiguity, and weakness in this text.
                    Cite specific risks.
                    
                    Text to Attack:
                    {text_to_attack}
                    """
                    response = model.generate_content(prompt)
                    st.markdown("### ⚠️ Risk Assessment")
                    st.write(response.text)
                except Exception as e:
                    # Fallback if 'latest' is not available in your region yet
                    try:
                        model = genai.GenerativeModel('gemini-pro')
                        response = model.generate_content(prompt)
                        st.markdown("### ⚠️ Risk Assessment (Fallback Model)")
                        st.write(response.text)
                    except:
                        st.error(f"Gemini Error: {e}")
