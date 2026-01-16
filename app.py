import streamlit as st
from supabase import create_client, Client
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Fortress Legal (Glass Box)", layout="wide")

try:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    google_api_key = st.secrets["GOOGLE_API_KEY"]
except KeyError:
    st.error("🚨 Secrets missing.")
    st.stop()

supabase: Client = create_client(supabase_url, supabase_key)
genai.configure(api_key=google_api_key)

# --- 2. SIDEBAR (Ingestion) ---
with st.sidebar:
    st.header("🗄️ Case Files")
    input_method = st.radio("Input", ["Upload Text", "Paste Text"])
    documents = []
    
    if input_method == "Upload Text":
        files = st.file_uploader("Upload .txt", type=["txt"], accept_multiple_files=True)
        if files:
            for f in files: documents.append(f.read().decode("utf-8", errors="ignore"))
    elif input_method == "Paste Text":
        text = st.text_area("Paste here")
        if text: documents.append(text)

    if st.button("Sync to Cloud"):
        if not documents:
            st.warning("No docs.")
        else:
            with st.spinner("Indexing..."):
                try:
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    SupabaseVectorStore.from_texts(
                        texts=documents, embedding=embeddings, client=supabase,
                        table_name="documents", query_name="match_documents"
                    )
                    st.success(f"✅ Indexed {len(documents)} files.")
                except Exception as e: st.error(f"Error: {e}")

# --- 3. MAIN APP ---
st.title("🛡️ Fortress Legal")
st.caption("Enterprise RAG | Evidence-Based Analysis")

tab1, tab2 = st.tabs(["📝 Evidence-Based Analysis", "⚖️ The Antagonist"])

# --- TAB 1: GLASS BOX RAG ---
with tab1:
    user_query = st.text_area("Ask a question about your files:", height=100)
    
    if st.button("Analyze"):
        if not user_query:
            st.warning("Please ask a question.")
        else:
            with st.spinner("Retrieving Evidence..."):
                try:
                    # 1. Setup Retrieval
                    embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
                    vector_store = SupabaseVectorStore(
                        client=supabase, embedding=embeddings, 
                        table_name="documents", query_name="match_documents"
                    )
                    
                    # RETRIEVER: Get top 4 most relevant chunks
                    retriever = vector_store.as_retriever(search_kwargs={"k": 4})
                    
                    # 2. Strict Legal Prompt
                    template = """
                    You are a strict legal research assistant. 
                    Answer the question based ONLY on the following context.
                    If the answer is not in the context, say "I cannot find this information in the provided documents."
                    Do not make up facts.
                    
                    Context:
                    {context}
                    
                    Question: {question}
                    """
                    prompt = PromptTemplate.from_template(template)
                    llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
                    
                    # 3. The "Transparent" Chain
                    # This captures BOTH the answer AND the source documents
                    rag_chain_from_docs = (
                        RunnablePassthrough.assign(context=(lambda x: x["context"]))
                        | prompt
                        | llm
                        | StrOutputParser()
                    )
                    
                    rag_chain_with_source = RunnableParallel(
                        {"context": retriever, "question": RunnablePassthrough()}
                    ).assign(answer=rag_chain_from_docs)
                    
                    # 4. Run it
                    result = rag_chain_with_source.invoke(user_query)
                    
                    # 5. Display Answer
                    st.markdown("### 📋 Analysis")
                    st.write(result["answer"])
                    
                    # 6. Display "Citations" (The actual text chunks used)
                    st.markdown("---")
                    st.markdown("#### 🔍 Evidence (Source Documents)")
                    st.caption("The AI read these exact snippets to form its answer:")
                    for i, doc in enumerate(result["context"]):
                        with st.expander(f"Source Snippet #{i+1}"):
                            st.info(doc.page_content)
                            
                except Exception as e:
                    st.error(f"Analysis Error: {e}")

# --- TAB 2: ANTAGONIST (Gemini) ---
with tab2:
    text_to_attack = st.text_area("Clause to attack:", height=100)
    if st.button("Simulate Attack"):
        try:
            model = genai.GenerativeModel('gemini-1.5-pro')
            st.write(model.generate_content(f"Destroy this legal clause: {text_to_attack}").text)
        except Exception as e: st.error(f"Error: {e}")
