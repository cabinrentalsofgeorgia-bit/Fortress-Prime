#!/usr/bin/env python3
"""
Module CF-03: Counselor CRM — Legal Intelligence API
=======================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All inference and storage on-premise. No cloud APIs.

FastAPI microservice exposing the Counselor CRM RAG pipeline.
Accepts natural language legal questions, retrieves context from Qdrant,
reasons with DeepSeek-R1 (Captain) or Qwen 2.5 (Muscle), and returns
cited legal analysis.

ENDPOINTS:
    POST /v1/ask          — Ask a legal question (full RAG pipeline)
    POST /v1/search       — Semantic search only (no LLM reasoning)
    POST /v1/ingest       — Trigger document ingestion for a directory
    GET  /v1/collection   — Collection stats and metadata
    GET  /health          — Service + Qdrant + LLM health check

DEPLOYMENT:
    uvicorn Modules.CF-03_CounselorCRM.api:app --host 0.0.0.0 --port 8002 --reload

SWAGGER:
    http://fortress.crog-ai.com:8002/docs

Author: Fortress Prime Architect
Version: 1.0.0
"""

import os
import sys
import re
import asyncio
import time
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import requests
import importlib.util

# ---------------------------------------------------------------------------
# Project root + dynamic imports (hyphen in CF-03 prevents normal import)
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_module_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _project_root)
from config import SPARK_02_IP


def _load_sibling(module_name: str, filename: str):
    """Dynamic import for modules in hyphenated directory names."""
    path = os.path.join(_module_dir, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Import sibling modules
_query_engine = _load_sibling("query_engine", "query_engine.py")
_ingest_docs = _load_sibling("ingest_docs", "ingest_docs.py")

retrieve = _query_engine.retrieve
build_context = _query_engine.build_context
ask_llm = _query_engine.ask_llm
embed_query = _query_engine.embed_query
strip_think_tags = _query_engine.strip_think_tags
QDRANT_URL = _query_engine.QDRANT_URL
QDRANT_HEADERS = _query_engine.QDRANT_HEADERS
COLLECTION_NAME = _query_engine.COLLECTION_NAME
CAPTAIN_MODEL = _query_engine.CAPTAIN_MODEL
MUSCLE_MODEL = _query_engine.MUSCLE_MODEL
FAST_MODEL = _query_engine.FAST_MODEL
DEFAULT_TOP_K = _query_engine.DEFAULT_TOP_K

discover_files = _ingest_docs.discover_files
classify_document = _ingest_docs.classify_document
get_collection_count = _ingest_docs.get_collection_count
EMBED_MODEL = _ingest_docs.EMBED_MODEL
EMBED_DIM = _ingest_docs.EMBED_DIM

logger = logging.getLogger("fortress.counselor_crm.api")

# =============================================================================
# FastAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="Crog-Fortress Counselor CRM API",
    description=(
        "**Module CF-03: Legal & Compliance Intelligence**\n\n"
        "RAG-powered legal document search and analysis for Cabin Rentals of Georgia.\n"
        "Retrieves relevant documents from Qdrant and reasons with local LLMs.\n\n"
        "**Data Sovereignty:** All embeddings, vectors, and reasoning stay on-premise.\n"
        "No OpenAI. No cloud APIs. Local Ollama cluster only."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "Fortress Prime Architect",
        "url": "https://fortress.crog-ai.com",
    },
    license_info={
        "name": "Proprietary — Cabin Rentals of Georgia",
    },
)


# =============================================================================
# PYDANTIC MODELS — THE CONTRACT
# =============================================================================

# --- Request Models ---

class AskRequest(BaseModel):
    """Full RAG query request: embed -> retrieve -> reason -> answer."""
    question: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Natural language legal question",
        examples=["What are the lease terms for Rolling River cabin?"],
    )
    brain: str = Field(
        default="fast",
        description="LLM to use: 'fast' (R1:8b, ~30s), 'captain' (R1:70b, ~5min), or 'muscle' (Qwen:72b, ~5min)",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=20,
        description="Number of document chunks to retrieve",
    )
    category: Optional[str] = Field(
        default=None,
        description="Filter by document category (e.g., 'lease_agreement', 'georgia_statute')",
    )
    score_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for retrieval",
    )


class SearchRequest(BaseModel):
    """Semantic search only (no LLM reasoning)."""
    query: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Search query for legal documents",
        examples=["easement agreement Morgan Ridge"],
    )
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=50)
    category: Optional[str] = None
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class IngestRequest(BaseModel):
    """Trigger document ingestion for a directory."""
    source_dir: str = Field(
        ...,
        description="Absolute path to the directory to scan",
        examples=["/mnt/fortress_nas/Corporate_Legal/"],
    )
    full_reindex: bool = Field(
        default=False,
        description="If true, re-index all files even if already present",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, count files without ingesting",
    )


# --- Response Models ---

class SourceDocument(BaseModel):
    """A source document referenced in the answer."""
    file_name: str
    category: str
    score: float = Field(description="Cosine similarity score (0-1)")
    source_file: str = Field(description="Full NAS path to the document")


class AskResponse(BaseModel):
    """Full RAG analysis response."""
    answer: str = Field(description="LLM-generated, cited legal analysis")
    sources: List[SourceDocument] = Field(description="Documents used as context")
    brain: str = Field(description="LLM used for reasoning")
    chunks_retrieved: int
    context_chars: int
    retrieval_time_s: float
    reasoning_time_s: float
    total_time_s: float
    timestamp: str


class SearchResult(BaseModel):
    """A single search result (chunk)."""
    text: str = Field(description="Document chunk text")
    file_name: str
    category: str
    parent_dir: str
    score: float
    chunk_index: int
    total_chunks: int


class SearchResponse(BaseModel):
    """Semantic search results (no LLM reasoning)."""
    query: str
    results: List[SearchResult]
    total_results: int
    retrieval_time_s: float


class IngestResponse(BaseModel):
    """Ingestion trigger response."""
    status: str
    source_dir: str
    files_found: int
    categories: Dict[str, int]
    message: str


class CollectionStats(BaseModel):
    """Qdrant collection statistics."""
    collection_name: str
    points_count: int
    vectors_count: int
    status: str
    segments_count: int
    embedding_model: str
    embedding_dim: int


class HealthResponse(BaseModel):
    """Service health check."""
    status: str
    module: str
    qdrant: Dict[str, Any]
    embedding_model: Dict[str, Any]
    llm_captain: Dict[str, Any]
    llm_muscle: Dict[str, Any]
    timestamp: str


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.post(
    "/v1/ask",
    response_model=AskResponse,
    tags=["Intelligence"],
    summary="Ask a legal question (full RAG pipeline)",
    description=(
        "Embeds the question, retrieves relevant legal documents from Qdrant, "
        "sends context to a local LLM (DeepSeek-R1 or Qwen 2.5), and returns "
        "a cited legal analysis. Every query is logged to the NAS audit trail."
    ),
)
async def ask_question(req: AskRequest):
    """Full RAG pipeline: embed -> retrieve -> reason -> cited answer."""
    loop = asyncio.get_event_loop()
    t_start = time.time()

    # Validate brain choice
    if req.brain not in ("captain", "muscle", "fast"):
        raise HTTPException(status_code=400, detail="brain must be 'fast', 'captain', or 'muscle'")

    # Run retrieval in thread pool (I/O bound: embedding call + Qdrant search)
    chunks = await loop.run_in_executor(
        None,
        lambda: retrieve(
            req.question,
            top_k=req.top_k,
            category=req.category,
            score_threshold=req.score_threshold,
        ),
    )
    retrieval_time = time.time() - t_start

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant documents found. Try a broader query or ingest more documents.",
        )

    # Build context and reason with LLM (CPU+network bound)
    context = build_context(chunks)
    t_reason = time.time()
    answer = await loop.run_in_executor(
        None,
        lambda: ask_llm(req.question, context, brain=req.brain),
    )
    reasoning_time = time.time() - t_reason
    total_time = time.time() - t_start

    # Build sources list
    sources = []
    seen = set()
    for c in chunks:
        key = c["file_name"]
        if key not in seen:
            sources.append(SourceDocument(
                file_name=c["file_name"],
                category=c["category"],
                score=round(c["score"], 4),
                source_file=c["source_file"],
            ))
            seen.add(key)

    return AskResponse(
        answer=answer,
        sources=sources,
        brain=req.brain,
        chunks_retrieved=len(chunks),
        context_chars=len(context),
        retrieval_time_s=round(retrieval_time, 3),
        reasoning_time_s=round(reasoning_time, 3),
        total_time_s=round(total_time, 3),
        timestamp=datetime.now().isoformat(),
    )


@app.post(
    "/v1/search",
    response_model=SearchResponse,
    tags=["Search"],
    summary="Semantic search (no LLM reasoning)",
    description=(
        "Embeds the query, searches Qdrant for the most relevant legal document "
        "chunks, and returns them directly. Useful for browsing the legal library."
    ),
)
async def semantic_search(req: SearchRequest):
    """Semantic search against the legal vector database."""
    loop = asyncio.get_event_loop()
    t_start = time.time()

    chunks = await loop.run_in_executor(
        None,
        lambda: retrieve(
            req.query,
            top_k=req.top_k,
            category=req.category,
            score_threshold=req.score_threshold,
        ),
    )
    retrieval_time = time.time() - t_start

    results = [
        SearchResult(
            text=c["text"],
            file_name=c["file_name"],
            category=c["category"],
            parent_dir=c["parent_dir"],
            score=round(c["score"], 4),
            chunk_index=c["chunk_index"],
            total_chunks=c["total_chunks"],
        )
        for c in chunks
    ]

    return SearchResponse(
        query=req.query,
        results=results,
        total_results=len(results),
        retrieval_time_s=round(retrieval_time, 3),
    )


@app.post(
    "/v1/ingest",
    response_model=IngestResponse,
    tags=["Ingestion"],
    summary="Trigger document ingestion (dry-run preview)",
    description=(
        "Scans a directory for legal documents and returns a file count / category "
        "breakdown. Set dry_run=false to actually ingest (long-running operation)."
    ),
)
async def trigger_ingest(req: IngestRequest):
    """Scan a directory and optionally trigger ingestion."""
    if not os.path.isdir(req.source_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Directory not found: {req.source_dir}",
        )

    loop = asyncio.get_event_loop()

    # Discover files
    files = await loop.run_in_executor(None, lambda: discover_files(req.source_dir))

    categories: Dict[str, int] = {}
    for f in files:
        cat = classify_document(f)
        categories[cat] = categories.get(cat, 0) + 1

    if req.dry_run or len(files) == 0:
        return IngestResponse(
            status="dry_run" if req.dry_run else "empty",
            source_dir=req.source_dir,
            files_found=len(files),
            categories=categories,
            message=f"Found {len(files)} documents. Set dry_run=false to begin ingestion.",
        )

    # Run ingestion in background (this is a long-running operation)
    # For now, we return the preview and let the user trigger via CLI
    return IngestResponse(
        status="preview",
        source_dir=req.source_dir,
        files_found=len(files),
        categories=categories,
        message=(
            f"Found {len(files)} documents ready for ingestion. "
            "For production ingestion, use the CLI: "
            f"python3 -m Modules.CF-03_CounselorCRM.ingest_docs --source {req.source_dir}"
        ),
    )


@app.get(
    "/v1/collection",
    response_model=CollectionStats,
    tags=["Intelligence"],
    summary="Qdrant collection statistics",
)
async def collection_stats():
    """Get current state of the legal_library collection in Qdrant."""
    try:
        resp = requests.get(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            headers=QDRANT_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Qdrant collection not found")

        info = resp.json().get("result", {})
        return CollectionStats(
            collection_name=COLLECTION_NAME,
            points_count=info.get("points_count", 0),
            vectors_count=info.get("vectors_count", 0),
            status=info.get("status", "unknown"),
            segments_count=info.get("segments_count", 0),
            embedding_model=EMBED_MODEL,
            embedding_dim=EMBED_DIM,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Qdrant unreachable: {e}")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Operations"],
    summary="Service health check",
    description="Checks connectivity to Qdrant, embedding model, and both LLM nodes.",
)
async def health_check():
    """Full health check: Qdrant + embedding model + LLM nodes."""

    # Check Qdrant
    qdrant_status = {"status": "offline", "points": 0}
    try:
        resp = requests.get(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", headers=QDRANT_HEADERS, timeout=5)
        if resp.status_code == 200:
            info = resp.json().get("result", {})
            qdrant_status = {
                "status": "online",
                "url": QDRANT_URL,
                "collection": COLLECTION_NAME,
                "points": info.get("points_count", 0),
            }
    except Exception:
        qdrant_status["url"] = QDRANT_URL

    # Check embedding model
    embed_status = {"status": "offline", "model": EMBED_MODEL}
    try:
        resp = requests.post(
            "http://localhost:11434/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": "test"},
            timeout=10,
        )
        if resp.status_code == 200:
            emb = resp.json().get("embedding", [])
            embed_status = {
                "status": "online",
                "model": EMBED_MODEL,
                "dimensions": len(emb),
            }
    except Exception:
        pass

    # Check Captain LLM
    captain_status = {"status": "offline", "model": CAPTAIN_MODEL}
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            captain_status = {
                "status": "online" if any(CAPTAIN_MODEL.split(":")[0] in m for m in models) else "model_not_loaded",
                "model": CAPTAIN_MODEL,
                "node": "Captain (Spark 2)",
            }
    except Exception:
        pass

    # Check Muscle LLM
    muscle_status = {"status": "offline", "model": MUSCLE_MODEL}
    try:
        resp = requests.get(f"http://{SPARK_02_IP}:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            muscle_status = {
                "status": "online" if any(MUSCLE_MODEL.split(":")[0] in m for m in models) else "model_not_loaded",
                "model": MUSCLE_MODEL,
                "node": "Muscle (Spark 1)",
            }
    except Exception:
        pass

    # Overall status
    overall = "operational"
    if qdrant_status["status"] != "online":
        overall = "degraded"
    if embed_status["status"] != "online":
        overall = "critical"

    return HealthResponse(
        status=overall,
        module="CF-03 Counselor CRM",
        qdrant=qdrant_status,
        embedding_model=embed_status,
        llm_captain=captain_status,
        llm_muscle=muscle_status,
        timestamp=datetime.now().isoformat(),
    )


# =============================================================================
# STARTUP
# =============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("CF-03 Counselor CRM API starting...")
    logger.info(f"Qdrant:    {QDRANT_URL} / {COLLECTION_NAME}")
    logger.info(f"Embedding: {EMBED_MODEL} ({EMBED_DIM}-dim)")
    logger.info(f"Captain:   {CAPTAIN_MODEL}")
    logger.info(f"Muscle:    {MUSCLE_MODEL}")
    logger.info("Data Sovereignty: ALL inference local. No cloud APIs.")
