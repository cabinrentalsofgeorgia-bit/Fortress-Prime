# src/legal_analyst.py
"""
AI Legal Analyst — Fortress Prime
====================================
Combines structured RAG retrieval with DeepSeek-R1 reasoning
to answer legal questions with source citations.

Pipeline:
    Question -> Embed -> ChromaDB (fortress_knowledge) -> Context
    Context + Question -> DeepSeek-R1 (Senior Attorney prompt) -> Cited Analysis

Usage:
    python3 -m src.legal_analyst "Summarize the Higginbotham easement dispute."
    python3 -m src.legal_analyst "Who is the plaintiff in the gravel road case?" --limit 10
"""

import argparse
import json
import requests
import chromadb
from langchain_ollama import OllamaEmbeddings

# --- CONFIG ---
# ChromaDB — local NVMe (migrated from /mnt/ai_fast NFS 2026-02-10)
try:
    from src.fortress_paths import CHROMA_PATH as DB_PATH
except ImportError:
    DB_PATH = "/home/admin/fortress_fast/chroma_db"
COLLECTION_NAME = "fortress_knowledge"
EMBEDDING_MODEL = "nomic-embed-text"
REASONING_MODEL = "deepseek-r1:70b"  # The Big Brain (Captain)
# REASONING_MODEL = "qwen2.5:72b"    # The Coding/Drafting Brain (Muscle) - Optional switch
OLLAMA_URL = "http://localhost:11434"


def get_context(query: str, limit: int = 5) -> str:
    """Retrieves structured context from the Vector DB."""
    client = chromadb.PersistentClient(path=DB_PATH)
    embedding_func = OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_URL)
    collection = client.get_collection(name=COLLECTION_NAME)

    query_vec = embedding_func.embed_query(query)
    results = collection.query(query_embeddings=[query_vec], n_results=limit)

    context_blob = ""
    sources_seen = set()

    for i, doc in enumerate(results['documents'][0]):
        meta = results['metadatas'][0][i]
        source = meta.get('source', 'Unknown File')
        category = meta.get('category', '')
        h1 = meta.get('Header 1', '')
        h2 = meta.get('Header 2', '')
        h3 = meta.get('Header 3', '')

        # Build structured context path
        path_parts = [p for p in [h1, h2, h3] if p]
        path_str = " > ".join(path_parts) if path_parts else "Document Root"

        context_blob += (
            f"\n[SOURCE: {source} | CATEGORY: {category} | SECTION: {path_str}]\n"
            f"{doc}\n"
        )
        sources_seen.add(source)

    print(f"  Retrieved {len(results['documents'][0])} chunks from {len(sources_seen)} files.")
    return context_blob


def query_llm(prompt: str, context: str):
    """Sends the context + prompt to the Local LLM with streaming output."""
    system_prompt = (
        "You are a senior legal analyst for 'Cabin Rentals of Georgia'. "
        "You have access to the firm's internal case files. "
        "Answer the user's question based ONLY on the provided context. "
        "Cite your sources (filenames) explicitly. "
        "If the context is insufficient, state what is missing."
    )

    full_prompt = f"### CONTEXT ###\n{context}\n\n### QUESTION ###\n{prompt}"

    payload = {
        "model": REASONING_MODEL,
        "prompt": full_prompt,
        "system": system_prompt,
        "stream": True,
    }

    print(f"\n  Analyst ({REASONING_MODEL}) is thinking...\n")
    print("=" * 60)

    # Stream the response token-by-token
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, stream=True, timeout=600
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    body = json.loads(line)
                    if "response" in body:
                        print(body["response"], end="", flush=True)
    except requests.exceptions.Timeout:
        print("\n\n[TIMEOUT] The reasoning model took too long. Try a simpler question.")
    except Exception as e:
        print(f"\n\n[ERROR] {e}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="AI Legal Analyst Agent")
    parser.add_argument("query", type=str, help="The legal question to answer")
    parser.add_argument("--limit", type=int, default=7, help="How many case file chunks to read")
    args = parser.parse_args()

    print(f"\n  Searching case files for: '{args.query}'...")
    context = get_context(args.query, limit=args.limit)

    if not context.strip():
        print("  No relevant case files found.")
        return

    query_llm(args.query, context)


if __name__ == "__main__":
    main()
