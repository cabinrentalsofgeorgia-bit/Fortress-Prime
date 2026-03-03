"""
Fortress Prime — NVIDIA-Native Reranker
Uses Ollama's embedding model (nomic-embed-text) running on NVIDIA GPU
to rerank search results by cosine similarity.

Stays 100% in the NVIDIA/Ollama ecosystem. No HuggingFace, no pip extras.

Usage:
    from nvidia_reranker import rerank_documents
    ranked = rerank_documents("Who owns the land?", ["doc1 text", "doc2 text"])
"""
import requests
import math
import json

# --- CONFIG ---
OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"


def get_embeddings(texts, input_type="search_document"):
    """Get embeddings from Ollama's nomic-embed-text model (NVIDIA GPU)."""
    # nomic-embed-text supports task prefixes for better retrieval
    if input_type == "search_query":
        prefixed = [f"search_query: {t}" for t in texts]
    else:
        prefixed = [f"search_document: {t}" for t in texts]

    response = requests.post(OLLAMA_URL, json={
        "model": EMBED_MODEL,
        "input": prefixed
    }, timeout=30)

    if response.status_code != 200:
        raise Exception(f"Ollama embed error: {response.text}")

    data = response.json()
    return data["embeddings"]


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rerank_documents(query, documents, top_k=10):
    """
    Rerank documents by semantic similarity to the query.
    Uses NVIDIA GPU via Ollama's nomic-embed-text model.

    Args:
        query: The search query string
        documents: List of dicts with at least a 'text' key and optional metadata
        top_k: Number of top results to return

    Returns:
        List of dicts with 'score' added, sorted by relevance
    """
    if not documents:
        return []

    # Extract text for embedding
    doc_texts = []
    for doc in documents:
        if isinstance(doc, dict):
            doc_texts.append(doc.get('text', doc.get('document', '')))
        else:
            doc_texts.append(str(doc))

    # Get query embedding
    query_emb = get_embeddings([query], input_type="search_query")[0]

    # Get document embeddings (batch)
    # Process in batches of 32 to avoid overloading
    all_doc_embs = []
    batch_size = 32
    for i in range(0, len(doc_texts), batch_size):
        batch = doc_texts[i:i + batch_size]
        embs = get_embeddings(batch, input_type="search_document")
        all_doc_embs.extend(embs)

    # Compute similarity scores
    scored = []
    for i, doc in enumerate(documents):
        score = cosine_similarity(query_emb, all_doc_embs[i])
        if isinstance(doc, dict):
            result = doc.copy()
            result['score'] = score
        else:
            result = {'text': str(doc), 'score': score}
        scored.append(result)

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)

    return scored[:top_k]


def test_reranker():
    """Quick test to verify the reranker works."""
    print(f"NVIDIA RERANKER TEST")
    print(f"    Engine: Ollama -> {EMBED_MODEL}")
    print(f"    Endpoint: {OLLAMA_URL}\n")

    query = "Who owns the land at Toccoa Heights?"
    documents = [
        "The quick brown fox jumps over the dog.",
        "The warranty deed conveys title to Gary M. Knight for Lot 14 in Toccoa Heights subdivision.",
        "Python scripts are useful for automation and data processing.",
        "The plat of survey for Phase Two sets forth Lots 13-24 of the Subdivision.",
        "Invoice #9066 from Cabin Rentals of Georgia for cleaning services.",
    ]

    print(f"    Query: \"{query}\"\n")

    results = rerank_documents(query, documents)

    print(f"    RANKED RESULTS:")
    for i, r in enumerate(results):
        score = r['score']
        bar = "#" * max(1, int(score * 50))
        print(f"    #{i+1} [Score: {score:.4f}] {bar}")
        print(f"       {r['text'][:90]}")
        print()

    # Check if warranty deed is #1
    if "warranty" in results[0]['text'].lower():
        print("    PASS: Warranty deed correctly ranked #1")
    else:
        print("    NOTE: Check ranking — warranty deed should be #1")


if __name__ == "__main__":
    test_reranker()
