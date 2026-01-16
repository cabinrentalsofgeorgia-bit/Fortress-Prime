import streamlit as st
import os
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import google.generativeai as genai

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="Fortress Legal (Enterprise)", layout="wide")

# Initialize Keys
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

# Configure Gemini
genai.configure(api_key=google_api_key)

# --- 2. SIDEBAR: SYNC ENGINE ---
with st.sidebar:
    st.header("🗄️ Case Files")
    st.info("Files are stored securely in Supabase Cloud.")
    
    input_method = st.radio("Input Method", ["Upload Text File", "Paste Text"])
    documents = []
    
    if input_method == "Upload Text File":
        # FIX: Restrict to .txt only to prevent Unicode Errors
        uploaded_files = st.file_uploader("Upload Contracts (TXT only)", type=["txt"], accept_multiple_files=True)
        if uploaded_files:
            for uploaded_file in uploaded_files:
                # FIX: specific decoding to ignore errors
                text = uploaded_file.read().decode("utf-8", errors="ignore")
                documents.append(text)
                
    elif input_method == "Paste Text":
        pasted_text = st.text_area("Paste legal text here")
        if pasted_text:
            documents.append(pasted_text)

    if st.button("Sync to Secure Cloud"):
        if not documents:
            st.warning("Please provide content to sync.")
        else:
            with st.spinner("Encrypting and Vectorizing..."):
                try:
                    # Generate Embeddings & Store in Supabase
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    vector_store = SupabaseVectorStore.from_texts(
                        texts=documents,
                        embedding=embeddings,
                        client=supabase,
                        table_name="documents",
                        query_name="match_documents"
                    )
                    st.success(f"✅ Synced {len(documents)} documents to Fortress Cloud.")
                except Exception as e:
                    st.error(f"Sync Failed: {e}")

# --- 3. MAIN INTERFACE ---
st.title("🛡️ Fortress Legal")
st.caption("Enterprise AI | Dual-Model Intelligence Layer")

tab1, tab2 = st.tabs(["📝 Drafting & Analysis", "⚖️ The Antagonist (Gemini)"])

# --- TAB 1: OPENAI (The Drafter) ---
with tab1:
    user_query = st.text_area("What do you need to draft or analyze?", height=150)
    
    if st.button("Analyze with Fortress AI"):
        if not user_query:
            st.warning("Please enter a query.")
        else:
            with st.spinner("Retrieving Precedents..."):
                try:
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    vector_store = SupabaseVectorStore(
                        client=supabase, 
                        embedding=embeddings, 
                        table_name="documents",
                        query_name="match_documents"
                    )
                    retriever = vector_store.as_retriever()
                    
                    llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
                    template = """
                    You are a senior partner. Use the context to answer.
                    Context: {context}
                    Question: {question}
                    """
                    prompt = PromptTemplate.from_template(template)
                    chain = (
                        {"context": retriever, "question": RunnablePassthrough()}
                        | prompt
                        | llm
                        | StrOutputParser()
                    )
                    
                    response = chain.invoke(user_query)
                    st.markdown("### 📄 Legal Analysis")
                    st.write(response)
                except Exception as e:
                    st.error(f"Analysis Failed: {e}")

# --- TAB 2: GEMINI (The Antagonist) ---
with tab2:
    st.info("Gemini 'Red Team' Mode: Attacks your arguments.")
    argument_to_attack = st.text_area("Paste a clause to attack:", height=150)
    
    if st.button("Run Antagonist Simulation"):
        if not argument_to_attack:
            st.warning("Paste text first.")
        else:
            with st.spinner("Gemini is finding loopholes..."):
                try:
                    model = genai.GenerativeModel('gemini-1.5-pro')
                    prompt = f"Find every loophole in this legal text:\n{argument_to_attack}"
                    response = model.generate_content(prompt)
                    st.markdown("### ⚠️ Risk Assessment")
                    st.write(response.text)
                except Exception as e:
                    st.error(f"Simulation Failed: {e}")
