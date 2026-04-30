"""
Qdrant vector database client for the Fortress Guest Platform.

Provides connection management, collection initialization, and embedding
helpers for the FGP RAG pipeline. Uses nomic-embed-text (768-dim) via
Ollama's OpenAI-compatible endpoint as the primary embedding model, with
NVIDIA NIM E5 v5 (1024-dim) as a future upgrade path once the CUDA
runtime issue is resolved.

Collections:
  - historical_quotes: Guest inquiry + staff response pairs for few-shot RAG
  - fgp_knowledge:     General knowledge base entries
"""
from __future__ import annotations

from typing import List, Optional

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from backend.core.config import settings

logger = structlog.get_logger()

HISTORICAL_QUOTES_COLLECTION = "historical_quotes"

_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Return a singleton Qdrant client."""
    global _client
    if _client is None:
        _client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        logger.info("qdrant_client_initialized", url=settings.qdrant_url)
    return _client


def ensure_collection(
    name: str = HISTORICAL_QUOTES_COLLECTION,
    vector_size: int = 0,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
) -> None:
    """Create the collection if it doesn't already exist."""
    if vector_size == 0:
        vector_size = settings.embed_dim

    client = get_qdrant_client()
    collections = [c.name for c in client.get_collections().collections]
    if name in collections:
        logger.info("qdrant_collection_exists", name=name)
        return

    client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(
            size=vector_size,
            distance=distance,
        ),
    )
    logger.info("qdrant_collection_created", name=name, size=vector_size, distance=distance.value)


async def embed_text(text: str, input_type: str = "passage") -> List[float]:
    """
    Generate an embedding vector for the given text.

    Uses the Ollama OpenAI-compatible endpoint (nomic-embed-text, 768-dim).
    Falls back gracefully with an error log if the embedding service is down.

    Args:
        text: The text to embed.
        input_type: "passage" for documents being indexed, "query" for search.
                    (Only used by NIM E5; nomic-embed-text ignores this.)
    """
    url = f"{settings.embed_base_url}/v1/embeddings"
    payload = {
        "input": text,
        "model": settings.embed_model,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        embedding = data["data"][0]["embedding"]
        return embedding


def embed_text_sync(text: str) -> List[float]:
    """Synchronous embedding helper for standalone scripts."""
    url = f"{settings.embed_base_url}/v1/embeddings"
    payload = {
        "input": text,
        "model": settings.embed_model,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]


LEGAL_EMBED_MODEL = "legal-embed"
LEGAL_EMBED_DIM = 2048


async def embed_legal_query(text: str) -> List[float]:
    """
    Embed a query for retrieval against the sovereign legal-embed _v2 collections.

    Uses the LiteLLM gateway alias `legal-embed` (llama-nemotron-embed-1b-v2 on
    spark-3:8102 — see PR #300 §9). Returns a 2048-dim vector for cosine search
    against `legal_caselaw_v2` / `legal_library_v2`.

    Caller contract (verified PR #300 §9.5, enforced here):
      - input_type="query" — asymmetric encoder; passages are indexed with
        "passage", queries must use "query"
      - encoding_format="float" — NIM strictly validates; the OpenAI client's
        implicit None default is rejected with HTTP 400

    Authenticates with `settings.litellm_master_key` (Bearer). Raises on
    transport / auth / validation errors so callers can decide how to degrade.
    """
    base = settings.litellm_base_url.rstrip("/")
    url = f"{base}/embeddings"
    payload = {
        "input": text,
        "model": LEGAL_EMBED_MODEL,
        "input_type": "query",
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
