"""
DGX Spark Local Tools — Edge coprocessors for the Board of Directors
=====================================================================
Three dedicated hardware functions exposed as callable tools that the
Cloud Horsemen (Anthropic, Gemini, xAI, OpenAI) can invoke via function
calling to offload heavy computation to sovereign local GPU metal.

Architecture:
  Sparks 1&2 (Reasoner)  — Deep analysis of legal docs, contracts, zoning
  Spark 3    (Ocular)    — Vision processing for damage photos, inspections
  Spark 4    (Memory)    — Fast RAG retrieval from Qdrant fgp_knowledge

All payloads stay on the local 192.168.0.x LAN. PII never leaves the cluster.
"""

import base64
import time
from typing import Optional

import httpx
import structlog

from backend.core.config import settings
from backend.services.knowledge_retriever import semantic_search, format_context

logger = structlog.get_logger()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tool 1: Ocular Engine (Spark 3) — Vision
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def analyze_image_local(
    base64_image: str,
    prompt: str = "Describe what you see in this image in detail.",
) -> str:
    """Analyze an image using the local DGX Spark 3 vision model.

    This tool sends a base64-encoded image to the on-premise Ocular Engine
    (Llama-3.2-90B-Vision on Spark 3) for pixel-level analysis. Use this
    when a guest uploads a damage photo, a cleaner submits an inspection
    image, or any visual content needs interpretation.

    Args:
        base64_image: The image encoded as a base64 string (JPEG or PNG).
        prompt: A natural-language instruction telling the vision model
                what to look for (e.g. "List all visible damage in this
                photo of a cabin living room").

    Returns:
        A text description of what the vision model detected in the image.
        On failure, returns an error message string prefixed with [ERROR].
    """
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                settings.dgx_ocular_url,
                json={
                    "model": settings.dgx_ocular_model,
                    "prompt": prompt,
                    "images": [base64_image],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 1024},
                },
            )
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()
            latency = (time.perf_counter() - t0) * 1000

            logger.info(
                "dgx_ocular_complete",
                latency_ms=round(latency),
                chars=len(result),
            )
            return result

    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        logger.error("dgx_ocular_failed", error=str(e)[:200], latency_ms=round(latency))
        return f"[ERROR] Vision analysis failed: {str(e)[:200]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tool 2: Reasoner Engine (Sparks 1&2) — Deep Analysis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def deep_reason_local(
    complex_text: str,
    query: str,
) -> str:
    """Perform deep reasoning over complex text using the local DGX Reasoner.

    This tool sends long documents (legal contracts, zoning reports, property
    assessments, financial statements) to the clustered Sparks 1&2 running
    DeepSeek-R1 (671B) for chain-of-thought analysis. Use this when the
    orchestrator needs to analyze a rental agreement, extract legal clauses,
    review a 100-page zoning document, or perform any task requiring deep
    multi-step reasoning over large text.

    Args:
        complex_text: The full text of the document to analyze. Can be up
                      to 32K tokens. Legal docs, contracts, inspection
                      reports, financial statements, etc.
        query: A specific question or instruction about the document
               (e.g. "Extract all clauses related to pet damage liability
               and security deposit forfeiture").

    Returns:
        The reasoner's detailed analysis as plain text.
        On failure, returns an error message string prefixed with [ERROR].
    """
    full_prompt = f"""DOCUMENT:
{complex_text[:60000]}

ANALYSIS REQUEST:
{query}

Provide a thorough, structured analysis. Cite specific sections when relevant."""

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                settings.dgx_reasoner_url,
                json={
                    "model": settings.dgx_reasoner_model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096},
                },
            )
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()
            latency = (time.perf_counter() - t0) * 1000

            logger.info(
                "dgx_reasoner_complete",
                latency_ms=round(latency),
                chars=len(result),
                doc_chars=len(complex_text),
            )
            return result

    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        logger.error("dgx_reasoner_failed", error=str(e)[:200], latency_ms=round(latency))
        return f"[ERROR] Deep reasoning failed: {str(e)[:200]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tool 3: Memory Engine (Spark 4) — RAG Vector Search
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def query_local_rag(
    search_term: str,
    property_id: Optional[str] = None,
    db=None,
) -> str:
    """Search the local Qdrant knowledge base for contextually relevant information.

    This tool performs semantic vector search against the fgp_knowledge
    Qdrant collection (855+ embeddings of property descriptions, guest
    notes, and maintenance records). Use this when the orchestrator needs
    factual property information, historical guest notes, or operational
    context to answer a question accurately.

    Args:
        search_term: The natural-language search query (e.g. "What is the
                     WiFi password for Bear Creek Lodge?" or "Has there
                     been prior hot tub maintenance at this property?").
        property_id: Optional UUID of a specific property to bias results
                     toward. Pass None for cross-property search.
        db: Optional async database session for PostgreSQL fallback.
            If not provided, only Qdrant vector search is attempted.

    Returns:
        Formatted context string with the top matching knowledge entries.
        Returns "[NO RESULTS]" if nothing relevant was found.
        Returns an error string prefixed with [ERROR] on failure.
    """
    from uuid import UUID as _UUID

    pid = None
    if property_id:
        try:
            pid = _UUID(property_id)
        except (ValueError, TypeError):
            pass

    t0 = time.perf_counter()
    try:
        hits = await semantic_search(
            question=search_term,
            db=db,
            property_id=pid,
            top_k=5,
        )
        latency = (time.perf_counter() - t0) * 1000

        if not hits:
            logger.info("dgx_rag_no_results", query=search_term[:80], latency_ms=round(latency))
            return "[NO RESULTS]"

        context = format_context(hits, max_chars=3000)
        logger.info(
            "dgx_rag_complete",
            query=search_term[:80],
            results=len(hits),
            top_score=hits[0].get("score", 0),
            latency_ms=round(latency),
        )
        return context

    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        logger.error("dgx_rag_failed", error=str(e)[:200], latency_ms=round(latency))
        return f"[ERROR] RAG search failed: {str(e)[:200]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tool Schema Definitions (for LLM function calling)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DGX_TOOL_SCHEMAS = [
    {
        "name": "analyze_image_local",
        "description": (
            "Analyze an image using the local DGX vision model (Spark 3). "
            "Use for damage photos, inspection images, or any visual content. "
            "Accepts a base64-encoded image and a prompt describing what to look for. "
            "Returns a text description of what was detected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "base64_image": {
                    "type": "string",
                    "description": "The image encoded as a base64 string (JPEG or PNG).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Instruction for the vision model (e.g. 'List all visible damage').",
                },
            },
            "required": ["base64_image"],
        },
    },
    {
        "name": "deep_reason_local",
        "description": (
            "Perform deep chain-of-thought reasoning over a long document using "
            "the local DGX Reasoner (Sparks 1&2, DeepSeek-R1 671B). "
            "Use for legal contracts, zoning documents, financial analysis, or any "
            "task requiring multi-step reasoning over large text. "
            "Accepts the document text and a specific analysis query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "complex_text": {
                    "type": "string",
                    "description": "The full document text to analyze (up to 32K tokens).",
                },
                "query": {
                    "type": "string",
                    "description": "Specific question or analysis instruction about the document.",
                },
            },
            "required": ["complex_text", "query"],
        },
    },
    {
        "name": "query_local_rag",
        "description": (
            "Search the local Qdrant vector knowledge base for property info, "
            "guest notes, and maintenance records. Use when you need factual "
            "context about a specific property, historical guest interactions, "
            "or operational details. Returns the top 5 semantically relevant matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "property_id": {
                    "type": "string",
                    "description": "Optional property UUID to bias results toward.",
                },
            },
            "required": ["search_term"],
        },
    },
]

TOOL_DISPATCH = {
    "analyze_image_local": analyze_image_local,
    "deep_reason_local": deep_reason_local,
    "query_local_rag": query_local_rag,
}


def get_openai_tools() -> list[dict]:
    """Return tool schemas formatted for OpenAI/xAI/Gemini function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in DGX_TOOL_SCHEMAS
    ]


def get_anthropic_tools() -> list[dict]:
    """Return tool schemas formatted for Anthropic tool_use."""
    return DGX_TOOL_SCHEMAS


async def execute_tool_call(name: str, arguments: dict, db=None) -> str:
    """Execute a tool call by name with the given arguments."""
    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return f"[ERROR] Unknown tool: {name}"

    if name == "query_local_rag":
        arguments["db"] = db

    try:
        return await fn(**arguments)
    except Exception as e:
        logger.error("tool_execution_failed", tool=name, error=str(e)[:200])
        return f"[ERROR] Tool '{name}' failed: {str(e)[:200]}"
