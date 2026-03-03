#!/usr/bin/env python3
"""
Module CF-03: Counselor CRM — RAG Query Engine
=================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All inference local. No cloud APIs.

Retrieves relevant legal document chunks from Qdrant, assembles context,
and sends it to DeepSeek-R1 (Captain) or Qwen 2.5 (Muscle) for
grounded, cited legal analysis.

PIPELINE:
    Question -> Embed (nomic-embed-text) -> Retrieve (Qdrant)
             -> Filter by category/payload -> Reason (LLM)
             -> Strip <think> tags -> Return cited answer

CLUSTER EXECUTION:
    Captain Node — Embedding + DeepSeek-R1 reasoning
    Muscle Node  — Qwen2.5:72b reasoning (fallback / technical queries)
    NAS          — Qdrant vector database

USAGE:
    # Ask a question (uses Captain / DeepSeek by default)
    python3 -m Modules.CF-03_CounselorCRM.query_engine \\
        "What are the terms of the Rolling River lease?"

    # Use Muscle node for reasoning
    python3 -m Modules.CF-03_CounselorCRM.query_engine \\
        "Summarize the easement on Morgan Ridge" --brain muscle

    # Filter by document category
    python3 -m Modules.CF-03_CounselorCRM.query_engine \\
        "Show me property tax assessments" --category tax_document

    # Interactive mode
    python3 -m Modules.CF-03_CounselorCRM.query_engine --interactive

Author: Fortress Prime Architect
Version: 1.0.0
"""

import os
import re
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

import requests

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _project_root)

from src.context_compressor import compress_rag_context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Qdrant (runs on Captain Node via Docker; can be moved to NAS later)
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
COLLECTION_NAME = os.getenv("COUNSELOR_COLLECTION", "legal_library")

# Embedding (same model as ingestion — CRITICAL for alignment)
EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768

# LLM endpoints (local Ollama cluster)
CAPTAIN_URL = "http://localhost:11434/api/chat"
CAPTAIN_MODEL = os.getenv("CAPTAIN_MODEL", "deepseek-r1:70b")

from config import SPARK_02_IP
MUSCLE_URL = f"http://{SPARK_02_IP}:11434/api/chat"
MUSCLE_MODEL = os.getenv("MUSCLE_MODEL", "qwen2.5:72b")

# Fast brain for quick turnaround (8b on Captain)
FAST_URL = "http://localhost:11434/api/chat"
FAST_MODEL = os.getenv("FAST_MODEL", "deepseek-r1:8b")

# Retrieval parameters
DEFAULT_TOP_K = 6         # More context for legal docs
MAX_CONTEXT_CHARS = 10000  # Legal queries often need more context

# Logging
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs/counselor_crm"

logger = logging.getLogger("fortress.counselor_crm.query")


# =============================================================================
# SYSTEM PROMPT — SENIOR LEGAL ANALYST
# =============================================================================

COUNSELOR_SYSTEM_PROMPT = """You are the Fortress Prime Counselor — a Senior Legal Analyst
for Cabin Rentals of Georgia, a vacation rental property management company.

You answer legal and compliance questions using ONLY the provided document context.

RULES:
1. Base your answer EXCLUSIVELY on the provided context documents.
2. If the context does not contain sufficient information, say "The available
   documents do not contain enough information to answer this question" and
   suggest what type of document might help.
3. ALWAYS cite your sources. Use the format [Source: filename.pdf] after
   each claim derived from a specific document.
4. For legal documents, quote relevant passages directly using quotation marks.
5. Include specific dates, amounts, names, section numbers, and clause references.
6. If multiple documents discuss the same topic, note any conflicts or
   discrepancies between them.
7. Structure complex answers with clear headers.
8. NEVER provide legal advice. Always recommend consulting an attorney for
   decisions based on your analysis.

DOCUMENT CATEGORIES YOU MAY SEE:
- lease_agreement: Rental/lease contracts and amendments
- property_deed: Property titles, deeds, warranty deeds, plats, transfers
- easement: Easement agreements and rights-of-way
- contract: General business contracts, partnerships, MOUs
- insurance: Insurance policies and coverage documents
- tax_document: Property tax assessments, returns, filings
- permit_license: Building permits, business licenses, zoning
- court_filing: Pleadings, complaints, motions, orders, summons, subpoenas
- discovery_material: Document productions, interrogatories, records requests
- deposition_transcript: Sworn depositions and deposition exhibits
- billing_fees: Attorney fee records, invoices, billing statements
- georgia_statute: Official Code of Georgia Annotated (O.C.G.A.)
- local_regulation: County ordinances, HOA rules
- correspondence: Legal letters, notices, demand letters, LOAs
- general_legal: Uncategorized legal documents

CONTEXT FORMAT:
Each chunk includes: [Source File] [Category] [Chunk text]
"""


# =============================================================================
# EMBEDDING
# =============================================================================

def embed_query(text: str) -> Optional[List[float]]:
    """Generate embedding for a query string via local Ollama."""
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if emb and len(emb) == EMBED_DIM:
            return emb
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
    return None


# =============================================================================
# QDRANT RETRIEVAL
# =============================================================================

def retrieve(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    category: Optional[str] = None,
    score_threshold: float = 0.3,
    qdrant_url: str = QDRANT_URL,
) -> List[Dict[str, Any]]:
    """
    Retrieve the most relevant document chunks from Qdrant.

    Supports category-based filtering via Qdrant payload filters.
    Returns list of dicts with: text, source_file, category, score
    """
    # Embed the query
    query_embedding = embed_query(query)
    if not query_embedding:
        return []

    # Build Qdrant search request
    search_payload: Dict[str, Any] = {
        "vector": query_embedding,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
        "score_threshold": score_threshold,
    }

    # Category filter (Qdrant payload filtering)
    if category:
        search_payload["filter"] = {
            "must": [
                {"key": "category", "match": {"value": category}}
            ]
        }

    try:
        resp = requests.post(
            f"{qdrant_url}/collections/{COLLECTION_NAME}/points/search",
            json=search_payload,
            headers=QDRANT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
    except Exception as e:
        logger.error(f"Qdrant search failed: {e}")
        return []

    # Format results
    chunks = []
    for hit in results:
        payload = hit.get("payload", {})
        chunks.append({
            "text": payload.get("text", ""),
            "source_file": payload.get("source_file", "unknown"),
            "file_name": payload.get("file_name", "unknown"),
            "category": payload.get("category", "general_legal"),
            "parent_dir": payload.get("parent_dir", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "total_chunks": payload.get("total_chunks", 0),
            "score": hit.get("score", 0.0),
        })

    return chunks


# =============================================================================
# LLM REASONING
# =============================================================================

def build_context(chunks: List[Dict[str, Any]]) -> str:
    """Build the context string from retrieved chunks."""
    context_parts = []
    total_chars = 0

    for i, chunk in enumerate(chunks, 1):
        header = (
            f"[{i}] Source: {chunk['file_name']} | "
            f"Category: {chunk['category']} | "
            f"Score: {chunk['score']:.4f}"
        )
        entry = f"{header}\n{chunk['text']}\n"

        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            break

        context_parts.append(entry)
        total_chars += len(entry)

    return "\n---\n".join(context_parts)


def strip_think_tags(text: str) -> str:
    """
    Strip <think>...</think> tags from DeepSeek R1 output.
    Required per SOW Behavioral Protocol #5.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def ask_llm(
    query: str,
    context: str,
    brain: str = "captain",
) -> str:
    """
    Send query + context to the chosen LLM for grounded reasoning.

    brain: "captain" (DeepSeek-R1), "muscle" (Qwen 2.5), or "fast" (R1:8b)
    """
    if brain == "muscle":
        url = MUSCLE_URL
        model = MUSCLE_MODEL
    elif brain == "fast":
        url = FAST_URL
        model = FAST_MODEL
    else:
        url = CAPTAIN_URL
        model = CAPTAIN_MODEL

    user_prompt = f"""LEGAL QUESTION: {query}

DOCUMENT CONTEXT:
{context}

Provide a detailed, well-cited answer based ONLY on the above context.
Include specific document references, section numbers, and direct quotes where applicable."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": COUNSELOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,   # Low temperature for legal precision
            "num_predict": 4096,
        },
    }

    try:
        logger.info(f"Reasoning with {model} on {'Captain' if brain == 'captain' else 'Muscle'}...")
        resp = requests.post(url, json=payload, timeout=600)
        resp.raise_for_status()
        answer = resp.json()["message"]["content"]

        # Strip <think> tags from DeepSeek output (SOW Protocol #5)
        answer = strip_think_tags(answer)

        return answer
    except Exception as e:
        return f"[ERROR] LLM call failed: {e}"


# =============================================================================
# FULL RAG PIPELINE
# =============================================================================

def query(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    category: Optional[str] = None,
    brain: str = "captain",
    show_sources: bool = True,
    qdrant_url: str = QDRANT_URL,
) -> Dict[str, Any]:
    """
    Full RAG pipeline: embed -> retrieve (Qdrant) -> reason (LLM) -> answer.

    Returns a dict with: answer, sources, timing, metadata.
    """
    print(f"\n  Query: \"{question}\"")
    if category:
        print(f"  Filter: category={category}")
    print(f"  Brain: {brain}")

    # Step 1: Retrieve
    print(f"\n  [1/2] Retrieving top-{top_k} legal documents from Qdrant...")
    t0 = time.time()
    chunks = retrieve(
        question, top_k=top_k, category=category, qdrant_url=qdrant_url,
    )
    retrieval_time = time.time() - t0

    if not chunks:
        return {
            "answer": "No relevant documents found in the legal library. "
                      "Try a broader query or check that document ingestion has completed.",
            "sources": [],
            "retrieval_time_s": retrieval_time,
            "reasoning_time_s": 0,
            "brain": brain,
        }

    RAG_CONFIDENCE_THRESHOLD = 0.65
    top_score = chunks[0]["score"]
    if top_score < RAG_CONFIDENCE_THRESHOLD:
        logger.warning(
            "RAG threshold failure: top score %.4f < %.2f — aborting LLM generation",
            top_score,
            RAG_CONFIDENCE_THRESHOLD,
        )
        return {
            "answer": (
                "FORTRESS PROTOCOL: Insufficient legal precedent found in the "
                "Sovereign Knowledge Base (best match confidence: "
                f"{top_score:.1%}). Human counsel required."
            ),
            "sources": [
                {
                    "file_name": c["file_name"],
                    "category": c["category"],
                    "score": c["score"],
                    "source_file": c["source_file"],
                }
                for c in chunks[:3]
            ],
            "retrieval_time_s": round(retrieval_time, 3),
            "reasoning_time_s": 0,
            "brain": brain,
            "chunks_retrieved": len(chunks),
            "context_chars": 0,
            "aborted_below_threshold": True,
            "top_score": top_score,
        }

    print(f"        Found {len(chunks)} chunks in {retrieval_time:.2f}s")

    if show_sources:
        print("\n  Sources:")
        seen_files = set()
        for c in chunks:
            if c["file_name"] not in seen_files:
                print(f"    - {c['file_name']} ({c['category']}) [score: {c['score']:.4f}]")
                seen_files.add(c["file_name"])

    # Step 2: Build context, compress, and ask LLM
    raw_context = build_context(chunks)
    context = compress_rag_context(raw_context)
    print(f"\n  [2/2] Sending {len(context)} chars of context to LLM (compressed from {len(raw_context)})...")
    t0 = time.time()
    answer = ask_llm(question, context, brain=brain)
    reasoning_time = time.time() - t0
    print(f"        LLM responded in {reasoning_time:.1f}s")

    # Unique sources
    sources = []
    seen = set()
    for c in chunks:
        key = c["file_name"]
        if key not in seen:
            sources.append({
                "file_name": c["file_name"],
                "category": c["category"],
                "score": c["score"],
                "source_file": c["source_file"],
            })
            seen.add(key)

    return {
        "answer": answer,
        "sources": sources,
        "retrieval_time_s": round(retrieval_time, 3),
        "reasoning_time_s": round(reasoning_time, 3),
        "brain": brain,
        "chunks_retrieved": len(chunks),
        "context_chars": len(context),
    }


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def interactive_mode(
    brain: str = "captain",
    top_k: int = DEFAULT_TOP_K,
    qdrant_url: str = QDRANT_URL,
):
    """Interactive legal query terminal."""
    print("=" * 70)
    print("  CF-03 COUNSELOR CRM — LEGAL INTELLIGENCE TERMINAL")
    print("  Data Sovereignty: All reasoning local. No cloud APIs.")
    print("=" * 70)

    # Check Qdrant connection
    try:
        resp = requests.get(f"{qdrant_url}/collections/{COLLECTION_NAME}", headers=QDRANT_HEADERS, timeout=10)
        if resp.status_code == 200:
            count = resp.json().get("result", {}).get("points_count", 0)
            print(f"\n  Index: {count} vectors in '{COLLECTION_NAME}' @ {qdrant_url}")
        else:
            print(f"\n  [WARN] Collection '{COLLECTION_NAME}' not found.")
            return
    except Exception:
        print(f"\n  [WARN] Qdrant unreachable at {qdrant_url}")
        return

    print(f"  Brain: {brain} ({'DeepSeek-R1' if brain == 'captain' else 'Qwen 2.5'})")
    print(f"  Top-K: {top_k}")
    print("\n  Commands:")
    print("    /brain captain|muscle  - Switch LLM")
    print("    /topk N               - Change retrieval count")
    print("    /category NAME        - Filter by document category")
    print("    /categories           - List available categories")
    print("    /stats                - Show collection statistics")
    print("    /quit                 - Exit")
    print()

    category_filter = None

    while True:
        try:
            question = input("  Counselor > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Session ended.")
            break

        if not question:
            continue

        # Command handling
        if question.startswith("/"):
            parts = question.split(maxsplit=1)
            cmd = parts[0].lower()

            if cmd == "/quit":
                print("  Session ended.")
                break
            elif cmd == "/brain" and len(parts) > 1:
                brain = parts[1].strip().lower()
                model = CAPTAIN_MODEL if brain == "captain" else MUSCLE_MODEL
                print(f"  Brain switched to: {brain} ({model})")
            elif cmd == "/topk" and len(parts) > 1:
                top_k = int(parts[1].strip())
                print(f"  Top-K set to: {top_k}")
            elif cmd == "/category" and len(parts) > 1:
                cat = parts[1].strip().lower()
                if cat in ("none", "all"):
                    category_filter = None
                    print("  Category filter: NONE (all documents)")
                else:
                    category_filter = cat
                    print(f"  Category filter: {cat}")
            elif cmd == "/categories":
                print("\n  Available document categories:")
                for cat in [
                    "lease_agreement", "property_deed", "easement",
                    "contract", "insurance", "tax_document",
                    "permit_license", "court_filing", "discovery_material",
                    "deposition_transcript", "billing_fees", "georgia_statute",
                    "local_regulation", "correspondence", "general_legal",
                ]:
                    print(f"    - {cat}")
                print()
            elif cmd == "/stats":
                try:
                    resp = requests.get(
                        f"{qdrant_url}/collections/{COLLECTION_NAME}",
                        headers=QDRANT_HEADERS,
                        timeout=10,
                    )
                    info = resp.json().get("result", {})
                    print(f"\n  Collection: {COLLECTION_NAME}")
                    print(f"  Points:     {info.get('points_count', 0)}")
                    print(f"  Vectors:    {info.get('vectors_count', 0)}")
                    print(f"  Status:     {info.get('status', 'unknown')}")
                    segments = info.get("segments_count", 0)
                    print(f"  Segments:   {segments}")
                    print()
                except Exception as e:
                    print(f"  Error: {e}")
            else:
                print(f"  Unknown command: {cmd}")
            continue

        # Run RAG query
        result = query(
            question,
            top_k=top_k,
            category=category_filter,
            brain=brain,
            qdrant_url=qdrant_url,
        )

        print("\n" + "=" * 70)
        print("  COUNSELOR ANALYSIS")
        print("=" * 70)
        print(result["answer"])
        print("=" * 70)
        print(f"  Retrieved: {result['chunks_retrieved']} chunks")
        print(f"  Retrieval: {result['retrieval_time_s']}s | Reasoning: {result['reasoning_time_s']}s")
        print()

        # Audit log
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "queries.jsonl"), "a") as lf:
            lf.write(json.dumps({
                "question": question,
                "brain": brain,
                "top_k": top_k,
                "category": category_filter,
                "sources": [s["file_name"] for s in result.get("sources", [])],
                "retrieval_time_s": result["retrieval_time_s"],
                "reasoning_time_s": result["reasoning_time_s"],
                "timestamp": datetime.now().isoformat(),
            }) + "\n")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="CF-03 Counselor CRM — Legal RAG Query Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m Modules.CF-03_CounselorCRM.query_engine \\
      "What are the lease terms for Rolling River?"

  python3 -m Modules.CF-03_CounselorCRM.query_engine \\
      "O.C.G.A. easement rights" --category georgia_statute

  python3 -m Modules.CF-03_CounselorCRM.query_engine --interactive
        """,
    )
    parser.add_argument(
        "question", nargs="?", default=None,
        help="Legal question to ask (omit for interactive mode)",
    )
    parser.add_argument(
        "--brain", choices=["captain", "muscle"], default="captain",
        help="Which LLM to use (captain=DeepSeek, muscle=Qwen)",
    )
    parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K,
        help=f"Number of chunks to retrieve (default: {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--category", default=None,
        help="Filter by document category (lease_agreement, georgia_statute, etc.)",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Interactive query mode",
    )
    parser.add_argument(
        "--sources-only", action="store_true",
        help="Only show matching sources, don't send to LLM",
    )
    parser.add_argument(
        "--qdrant-url", default=QDRANT_URL,
        help=f"Qdrant REST URL (default: {QDRANT_URL})",
    )
    args = parser.parse_args()

    if args.interactive or args.question is None:
        interactive_mode(brain=args.brain, top_k=args.top_k, qdrant_url=args.qdrant_url)
    elif args.sources_only:
        chunks = retrieve(args.question, top_k=args.top_k, category=args.category, qdrant_url=args.qdrant_url)
        if chunks:
            print(f"\nTop {len(chunks)} matches for: \"{args.question}\"\n")
            for i, c in enumerate(chunks, 1):
                print(f"[{i}] {c['file_name']} ({c['category']}) - score: {c['score']:.4f}")
                print(f"    Dir: {c['parent_dir']}")
                print(f"    Preview: {c['text'][:200]}...")
                print()
        else:
            print("No matching documents found.")
    else:
        result = query(
            args.question,
            top_k=args.top_k,
            category=args.category,
            brain=args.brain,
            qdrant_url=args.qdrant_url,
        )
        print("\n" + "=" * 70)
        print("  COUNSELOR ANALYSIS")
        print("=" * 70)
        print(result["answer"])
        print("=" * 70)
