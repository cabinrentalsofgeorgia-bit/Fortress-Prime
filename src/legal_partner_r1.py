"""
Fortress Prime — Legal Partner R1 (Taylor Persona Engine)
==========================================================
The Senior Managing Partner with Taylor Knight's voice.

Combines:
    1. LEGAL PRECEDENT   — from the 157K-vector Vault (fortress_docs)
    2. FINANCIAL DATA     — from the Shadow Ledger (PostgreSQL)
    3. VISUAL AMENITIES   — from The Eye (vision scan metadata)
    4. TAYLOR'S VOICE     — training_gold persona data in ChromaDB

When drafting marketing copy, owner communications, or guest-facing
content, R1 channels Taylor's warm, sophisticated writing style.
When doing legal analysis, it stays sharp and objective.

Usage:
    # CLI — direct consultation
    python3 -m src.legal_partner_r1 "Draft the Rivers Edge corporate retreat email."
    python3 -m src.legal_partner_r1 "Analyze the Higginbotham easement risk." --mode legal

    # Module — import into other systems
    from src.legal_partner_r1 import consult_partner
    result = consult_partner("Draft the Rivers Edge email in Taylor's voice.")

Module: CF-03 Iron Mountain — Senior Partner + Persona Layer
"""

import os
import re
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
import chromadb

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ── Fortress imports ──
try:
    from src.fortress_paths import CHROMA_PATH
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import CHROMA_PATH

logger = logging.getLogger("fortress.partner_r1")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Ollama on Captain
OLLAMA_URL     = os.getenv("LLM_URL", "http://localhost:11434/api/chat")
LLM_MODEL      = os.getenv("LLM_MODEL", "deepseek-r1:70b")
LLM_FAST       = os.getenv("LLM_FAST", "deepseek-r1:8b")
EMBED_URL      = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL    = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ChromaDB — use HTTP client if server is running, fall back to persistent
CHROMA_HOST    = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT    = int(os.getenv("CHROMA_PORT", "8002"))
COLLECTION     = os.getenv("LEGAL_COLLECTION", "fortress_docs")

# How many persona examples to pull for voice calibration
PERSONA_EXAMPLES = 5
# How many legal/general context chunks to pull
CONTEXT_CHUNKS   = 8

# Collection names
PERSONA_COLLECTION = "taylor_voice"    # Dedicated persona collection (clean index)
LEGAL_COLLECTION   = COLLECTION        # Legal precedent (fortress_docs)


# =============================================================================
# SYSTEM PROMPT — TAYLOR PERSONA + LEGAL PARTNER
# =============================================================================

PARTNER_SYSTEM_PROMPT = """You are the Senior Managing Partner of Cabin Rentals of Georgia.

CRITICAL INSTRUCTION: VOICE & TONE
You must adopt the writing style of **Taylor Knight**.
- Tone: Warm, Sophisticated, Personal, "Southern Hospitality meets Luxury."
- Style: Use specific emotional triggers (e.g., "sunrise," "sanctuary," "memories," "crackling fire," "mountain air").
- Sentence flow: Conversational yet polished. Short punchy sentences mixed with longer, evocative ones.
- Avoid: Generic corporate speak ("valued customer," "best regards," "we appreciate your business").
- Instead of "Dear HR Director," use something like "Picture this..." or "Imagine your team..."
- When describing properties, paint a sensory picture. Mention specific amenities as lifestyle moments, not bullet points.

PERSONA TRAINING DATA:
Below are REAL examples of how Taylor writes. Study the rhythm, word choice, and emotional cadence.
Then MIMIC this voice precisely in your response.

{persona_examples}

INPUTS:
1. LEGAL PRECEDENT (From the 157K-Vector Library)
2. FINANCIAL DATA (From the Shadow Ledger)
3. VISUAL AMENITIES (From The Eye — cabin scans, photos, feature detection)

INSTRUCTIONS:
- If writing MARKETING or OWNER COMMUNICATIONS: MIMIC TAYLOR'S STYLE EXACTLY.
  Lead with emotion, then weave in specifics. Make the reader feel the cabin before seeing the price.
- If writing GUEST COMMUNICATIONS: Be warm but professional. Taylor's touch, firm's authority.
- If analyzing LEGAL RISK: Stay sharp and objective. Use White-Shoe firm precision.
  Still cite sources, still be thorough, but drop the marketing warmth.
- If doing FINANCIAL ANALYSIS: Quote exact figures from the Shadow Ledger.
  Combine Taylor's accessible style with hard data: "Rivers Edge didn't just perform — 
  it generated $47,200 in Q4 alone, a 23% increase over last year."

FORMATTING:
- For emails/letters: Use natural paragraphs, not corporate bullet points.
- For legal memos: Use structured headers, citations, and formal analysis.
- For financial reports: Data-forward with Taylor's narrative framing.
- ALWAYS cite sources: [Source: filename] for legal docs, [Source: Shadow Ledger] for financials.
"""


# =============================================================================
# CHROMADB CLIENT
# =============================================================================

_chroma_client = None

def get_chroma():
    """Get ChromaDB client — tries HTTP server first, falls back to persistent."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    # Try HTTP client first (for running chroma server)
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        client.heartbeat()
        _chroma_client = client
        logger.info(f"Connected to ChromaDB HTTP server at {CHROMA_HOST}:{CHROMA_PORT}")
        return client
    except Exception:
        pass

    # Fall back to persistent client (direct NVMe access)
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _chroma_client = client
        logger.info(f"Connected to ChromaDB persistent at {CHROMA_PATH}")
        return client
    except Exception as e:
        raise RuntimeError(f"Cannot connect to ChromaDB: {e}")


# =============================================================================
# EMBEDDING
# =============================================================================

def embed_text(text: str) -> List[float]:
    """Generate embedding via Ollama nomic-embed-text."""
    resp = requests.post(
        EMBED_URL,
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("embedding", [])


# =============================================================================
# RETRIEVAL — PERSONA + CONTEXT
# =============================================================================

def get_taylor_voice(query: str, n: int = PERSONA_EXAMPLES) -> str:
    """
    Retrieve Taylor's persona examples from the dedicated taylor_voice collection.
    Returns formatted examples for the system prompt.
    """
    try:
        client = get_chroma()
        collection = client.get_or_create_collection(PERSONA_COLLECTION)

        # Semantic search within Taylor's persona data
        query_vec = embed_text(query)
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=n,
            include=["documents", "metadatas"],
        )

        if not results["documents"] or not results["documents"][0]:
            return "(No Taylor persona examples found. Use your best judgment on warm, luxury tone.)"

        examples = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            subject = meta.get("subject", "")
            date = meta.get("date", "")
            header = f"--- Example {i+1}"
            if subject:
                header += f" | Re: {subject}"
            if date:
                header += f" | {date}"
            header += " ---"
            examples.append(f"{header}\n{doc[:1500]}")  # Cap length per example

        return "\n\n".join(examples)

    except Exception as e:
        logger.warning(f"Taylor voice retrieval failed: {e}")
        return "(Persona database unavailable. Default to warm, sophisticated Southern hospitality tone.)"


def get_legal_context(query: str, n: int = CONTEXT_CHUNKS) -> str:
    """
    Retrieve legal/general context from ChromaDB (fortress_docs collection).
    Falls back gracefully if the legal collection index is unavailable.
    """
    try:
        client = get_chroma()
        collection = client.get_collection(LEGAL_COLLECTION)

        query_vec = embed_text(query)
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return ""

        parts = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            source = meta.get("file_name", meta.get("source", "unknown"))
            category = meta.get("category", meta.get("type", "general"))
            dist = results["distances"][0][i] if results.get("distances") else None
            score_str = f" (score: {dist:.3f})" if dist is not None else ""
            parts.append(f"[{i+1}] Source: {source} | Category: {category}{score_str}\n{doc}")

        return "\n---\n".join(parts)

    except Exception as e:
        logger.warning(f"Legal context retrieval failed: {e}")
        return ""


# =============================================================================
# DEEPSEEK R1 — REASONING ENGINE
# =============================================================================

def strip_think_tags(text: str) -> str:
    """Strip <think>...</think> blocks from DeepSeek R1 output (SOW Protocol #5)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def consult_partner(
    query: str,
    mode: str = "auto",
    fast: bool = False,
    extra_context: str = "",
    stream: bool = False,
) -> Dict[str, Any]:
    """
    The Senior Partner thinks — with Taylor's voice when appropriate.

    Args:
        query:         What to ask/draft/analyze.
        mode:          "marketing", "legal", "financial", or "auto" (detect from query).
        fast:          Use 8b model instead of 70b.
        extra_context: Additional context (e.g., from The Eye's vision scan).
        stream:        If True, streams tokens to stdout and returns final text.

    Returns:
        Dict with answer, model, timing, sources, persona_loaded, etc.
    """
    t0 = time.time()
    model = LLM_FAST if fast else LLM_MODEL

    # ── 1. Retrieve Taylor's Voice ──
    print("  [1/3] Retrieving Taylor's voice from persona database...")
    persona_text = get_taylor_voice(query)
    persona_time = time.time() - t0

    # ── 2. Retrieve Legal/General Context ──
    print("  [2/3] Searching the Vault for relevant precedent...")
    legal_context = get_legal_context(query)
    context_time = time.time() - t0 - persona_time

    # ── 3. Build the Prompt ──
    system = PARTNER_SYSTEM_PROMPT.replace("{persona_examples}", persona_text)

    # Assemble user message with all context
    sections = [f"REQUEST: {query}"]

    if legal_context:
        sections.append(f"\nLEGAL PRECEDENT:\n{legal_context}")

    if extra_context:
        sections.append(f"\nADDITIONAL CONTEXT (Vision/Financial):\n{extra_context}")

    user_prompt = "\n".join(sections)

    # Adjust temperature based on mode
    if mode == "legal":
        temperature = 0.2  # Precise
    elif mode == "marketing":
        temperature = 0.7  # Creative
    elif mode == "financial":
        temperature = 0.3  # Data-precise but readable
    else:
        # Auto-detect: if query mentions marketing/email/draft/write → creative
        creative_signals = ["draft", "write", "email", "marketing", "owner letter",
                           "retreat", "listing", "describe", "pitch", "guest"]
        if any(sig in query.lower() for sig in creative_signals):
            temperature = 0.7
        else:
            temperature = 0.3

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": stream,
        "options": {
            "temperature": temperature,
            "num_predict": 4096,
        },
    }

    # ── 4. Send to R1 ──
    print(f"  [3/3] Senior Partner ({model}) is thinking (temp={temperature})...")
    reasoning_t0 = time.time()

    try:
        if stream:
            # Stream tokens to stdout
            full_response = ""
            print("\n" + "=" * 65)
            with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=600) as r:
                r.raise_for_status()
                in_think = False
                for line in r.iter_lines():
                    if line:
                        body = json.loads(line)
                        token = body.get("message", {}).get("content", "")
                        full_response += token
                        # Strip <think> tags in real-time
                        if "<think>" in token:
                            in_think = True
                        elif "</think>" in token:
                            in_think = False
                            continue
                        if not in_think:
                            print(token, end="", flush=True)
            print("\n" + "=" * 65)
            answer = strip_think_tags(full_response)
        else:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"]
            answer = strip_think_tags(raw)

        reasoning_time = time.time() - reasoning_t0
        total_time = time.time() - t0

        return {
            "answer": answer,
            "model": model,
            "mode": mode,
            "temperature": temperature,
            "persona_loaded": "(No Taylor persona" not in persona_text,
            "persona_examples": persona_text.count("--- Example"),
            "legal_chunks": legal_context.count("[") if legal_context else 0,
            "persona_time_s": round(persona_time, 2),
            "context_time_s": round(context_time, 2),
            "reasoning_time_s": round(reasoning_time, 2),
            "total_time_s": round(total_time, 2),
        }

    except Exception as e:
        return {
            "answer": f"[PARTNER ERROR] R1 consultation failed: {e}",
            "model": model,
            "error": str(e),
            "total_time_s": round(time.time() - t0, 2),
        }


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Senior Partner R1 (Taylor Persona)"
    )
    parser.add_argument("query", type=str, help="What to ask/draft/analyze")
    parser.add_argument("--mode", choices=["auto", "marketing", "legal", "financial"],
                        default="auto", help="Response mode")
    parser.add_argument("--fast", action="store_true", help="Use 8b model")
    parser.add_argument("--context", type=str, default="",
                        help="Additional context (paste from The Eye, etc.)")
    args = parser.parse_args()

    print("=" * 65)
    print("  FORTRESS PRIME — SENIOR PARTNER CONSULTATION")
    print("  Voice: Taylor Knight | Engine: DeepSeek-R1")
    print("=" * 65)

    result = consult_partner(
        query=args.query,
        mode=args.mode,
        fast=args.fast,
        extra_context=args.context,
        stream=True,  # Always stream in CLI mode
    )

    # Print metadata
    print(f"\n  Model:     {result.get('model')}")
    print(f"  Mode:      {result.get('mode')} (temp={result.get('temperature', '?')})")
    print(f"  Persona:   {'LOADED' if result.get('persona_loaded') else 'UNAVAILABLE'}"
          f" ({result.get('persona_examples', 0)} examples)")
    print(f"  Context:   {result.get('legal_chunks', 0)} legal chunks")
    print(f"  Timing:    persona={result.get('persona_time_s', 0)}s"
          f" | context={result.get('context_time_s', 0)}s"
          f" | reasoning={result.get('reasoning_time_s', 0)}s"
          f" | total={result.get('total_time_s', 0)}s")
    print("=" * 65)


if __name__ == "__main__":
    main()
