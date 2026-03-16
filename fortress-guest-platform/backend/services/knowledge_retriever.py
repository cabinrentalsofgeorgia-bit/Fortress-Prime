"""
Semantic Knowledge Retriever — Qdrant vector search with PostgreSQL fallback
=============================================================================
Provides a single async function that both the Agentic Orchestrator and the
Guest Portal Service call to retrieve contextually relevant knowledge.

Pipeline:
  1. Embed the query via local NIM (nomic-embed-text, 768-dim)
  2. Search fgp_knowledge Qdrant collection (top-K cosine similarity)
  3. On ANY failure, fall back to legacy PostgreSQL keyword search

This keeps Qdrant coupling in one place instead of scattered across services.
"""

from typing import List, Dict, Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.qdrant import COLLECTION_NAME, VECTOR_DIM
from backend.models.knowledge import KnowledgeBaseEntry

logger = structlog.get_logger()

EMBED_URL = "http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
DEFAULT_TOP_K = 5


async def _embed_query(text: str) -> Optional[List[float]]:
    """Vectorize a query string via the local NIM embedding endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding", [])
            if len(vec) == VECTOR_DIM:
                return vec
            logger.warning("query_embedding_dim_mismatch", expected=VECTOR_DIM, got=len(vec))
            return None
    except Exception as e:
        logger.warning("query_embedding_failed", error=str(e)[:200])
        return None


async def _qdrant_search(
    query_vector: List[float],
    top_k: int = DEFAULT_TOP_K,
    property_id: Optional[UUID] = None,
) -> List[Dict]:
    """Execute a similarity search against the fgp_knowledge Qdrant collection.

    When *property_id* is supplied the search is scoped to points that either
    belong to that property or have no property_id (global entries).
    """
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    body: Dict = {
        "vector": query_vector,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }

    if property_id is not None:
        body["filter"] = {
            "should": [
                {"key": "property_id", "match": {"value": str(property_id)}},
                {"is_empty": {"key": "property_id"}},
            ]
        }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{qdrant_url}/collections/{COLLECTION_NAME}/points/search",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])

    hits = []
    for pt in results:
        payload = pt.get("payload", {})
        text = payload.get("text", "")
        if text:
            hits.append({
                "text": text,
                "score": pt.get("score", 0.0),
                "source_table": payload.get("source_table", ""),
                "record_id": payload.get("record_id", ""),
                "name": payload.get("name", ""),
                "category": payload.get("category", ""),
            })
    return hits


async def _pg_keyword_fallback(
    question: str,
    property_id: Optional[UUID],
    db: AsyncSession,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict]:
    """Legacy PostgreSQL keyword search against knowledge_base_entries."""
    words = set(question.lower().split())
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "do", "does",
        "how", "what", "where", "when", "can", "i", "my", "we", "our",
        "to", "in", "at", "on", "for", "of", "and", "or", "it", "this",
    }
    keywords = words - stop_words
    if not keywords:
        return []

    filters = [KnowledgeBaseEntry.is_active == True]  # noqa: E712
    if property_id:
        filters.append(
            or_(
                KnowledgeBaseEntry.property_id == property_id,
                KnowledgeBaseEntry.property_id.is_(None),
            )
        )
    else:
        filters.append(KnowledgeBaseEntry.property_id.is_(None))

    result = await db.execute(
        select(KnowledgeBaseEntry).where(and_(*filters))
    )
    entries = result.scalars().all()

    scored = []
    for e in entries:
        entry_text = f"{e.question or ''} {e.answer} {' '.join(e.keywords or [])}".lower()
        score = 0.0
        for kw in keywords:
            if kw in entry_text:
                score += 1.0
                if e.question and kw in e.question.lower():
                    score += 0.5
                if e.keywords and kw in [k.lower() for k in e.keywords]:
                    score += 0.5
        if e.property_id is not None:
            score *= 1.5
        if score > 0:
            scored.append({
                "text": e.answer or "",
                "score": score,
                "source_table": "knowledge_base_entries",
                "record_id": str(e.id),
                "name": e.question or "",
                "category": e.category or "",
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


async def semantic_search(
    question: str,
    db: AsyncSession,
    property_id: Optional[UUID] = None,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict]:
    """Primary retrieval function. Tries Qdrant vector search first,
    falls back to PostgreSQL keyword search on any failure.

    Returns a list of dicts with keys: text, score, source_table,
    record_id, name, category.
    """
    try:
        query_vector = await _embed_query(question)
        if query_vector is not None:
            hits = await _qdrant_search(query_vector, top_k=top_k, property_id=property_id)
            if hits:
                logger.info(
                    "qdrant_semantic_search_hit",
                    query=question[:80],
                    results=len(hits),
                    top_score=hits[0]["score"],
                )
                return hits
            logger.info("qdrant_search_empty_fallback_to_pg", query=question[:80])
    except Exception as e:
        logger.warning("qdrant_search_failed_fallback_to_pg", error=str(e)[:200])

    pg_results = await _pg_keyword_fallback(question, property_id, db, top_k)
    if pg_results:
        logger.info("pg_keyword_fallback_hit", query=question[:80], results=len(pg_results))
    return pg_results


async def sync_knowledge_base_to_qdrant(db: AsyncSession) -> int:
    """Embed all active knowledge_base_entries and upsert into Qdrant.

    Returns the number of entries successfully synced.  Designed to be
    called at startup and periodically (e.g. hourly) so new KB entries
    automatically become searchable.
    """
    from backend.core.qdrant import ensure_payload_index

    await ensure_payload_index("property_id")
    await ensure_payload_index("category")

    result = await db.execute(
        select(KnowledgeBaseEntry).where(KnowledgeBaseEntry.is_active == True)  # noqa: E712
    )
    entries = result.scalars().all()
    if not entries:
        logger.info("kb_sync_no_entries")
        return 0

    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    synced = 0
    batch_points: List[Dict] = []

    for entry in entries:
        text_to_embed = f"{entry.question or ''}\n{entry.answer or ''}".strip()
        if not text_to_embed:
            continue

        vec = await _embed_query(text_to_embed)
        if vec is None:
            continue

        point_id = str(entry.qdrant_point_id or entry.id)
        payload: Dict = {
            "source_table": "knowledge_base_entries",
            "record_id": str(entry.id),
            "text": entry.answer or "",
            "name": entry.question or "",
            "category": entry.category or "",
        }
        if entry.property_id:
            payload["property_id"] = str(entry.property_id)

        batch_points.append({
            "id": point_id,
            "vector": vec,
            "payload": payload,
        })

        if len(batch_points) >= 50:
            await _upsert_batch(qdrant_url, headers, batch_points)
            synced += len(batch_points)
            batch_points = []

    if batch_points:
        await _upsert_batch(qdrant_url, headers, batch_points)
        synced += len(batch_points)

    logger.info("kb_sync_complete", synced=synced, total_entries=len(entries))
    return synced


async def _upsert_batch(
    qdrant_url: str,
    headers: Dict,
    points: List[Dict],
) -> None:
    """Upsert a batch of points into Qdrant."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(
            f"{qdrant_url}/collections/{COLLECTION_NAME}/points",
            json={"points": points},
            headers=headers,
        )
        resp.raise_for_status()


LEGAL_COLLECTION = "legal_library"


async def _qdrant_legal_search(
    query_vector: List[float],
    owner_id: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict]:
    """Search the legal_library Qdrant collection for management contract chunks.

    Scopes to the owner's contracts when *owner_id* is supplied, plus any
    documents without an owner_id (global contracts / templates).
    """
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    body: Dict = {
        "vector": query_vector,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }

    filter_clauses: List[Dict] = [
        {"key": "category", "match": {"value": "management_contract"}},
    ]

    if owner_id:
        body["filter"] = {
            "must": filter_clauses,
            "should": [
                {"key": "owner_id", "match": {"value": str(owner_id)}},
                {"is_empty": {"key": "owner_id"}},
            ],
        }
    else:
        body["filter"] = {"must": filter_clauses}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{qdrant_url}/collections/{LEGAL_COLLECTION}/points/search",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])

    hits = []
    for pt in results:
        payload = pt.get("payload", {})
        text = payload.get("text", "")
        if text:
            hits.append({
                "text": text,
                "score": pt.get("score", 0.0),
                "source_file": payload.get("source_file", payload.get("filename", "")),
                "category": payload.get("category", ""),
                "chunk_index": payload.get("chunk_index", 0),
            })
    return hits


async def legal_library_search(
    question: str,
    owner_id: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict]:
    """Retrieve management contract chunks from the legal_library Qdrant collection.

    Returns a list of dicts: text, score, source_file, category, chunk_index.
    Falls back to empty list on any failure (the concierge continues without
    contract context rather than crashing).
    """
    try:
        query_vector = await _embed_query(question)
        if query_vector is None:
            logger.warning("legal_library_embed_failed", query=question[:80])
            return []

        hits = await _qdrant_legal_search(query_vector, owner_id=owner_id, top_k=top_k)
        if hits:
            logger.info(
                "legal_library_search_hit",
                query=question[:80],
                results=len(hits),
                top_score=hits[0]["score"],
            )
        return hits
    except Exception as e:
        logger.warning("legal_library_search_failed", error=str(e)[:200])
        return []


def format_legal_context(hits: List[Dict], max_chars: int = 4000) -> str:
    """Format legal_library hits with source citation for LLM injection."""
    if not hits:
        return ""
    parts = []
    total = 0
    for h in hits:
        text = h.get("text", "").strip()
        if not text:
            continue
        source = h.get("source_file", "unknown")
        entry = f"[Source: {source}] {text}"
        if total + len(entry) > max_chars:
            break
        parts.append(entry)
        total += len(entry)
    return "\n\n".join(parts)


def format_context(hits: List[Dict], max_chars: int = 3000) -> str:
    """Format retrieval hits into a single context string for LLM injection."""
    if not hits:
        return ""
    parts = []
    total = 0
    for h in hits:
        text = h.get("text", "").strip()
        if not text:
            continue
        source = h.get("source_table", "")
        name = h.get("name", "")
        prefix = f"[{source}] {name}: " if name else f"[{source}] " if source else ""
        entry = f"{prefix}{text}"
        if total + len(entry) > max_chars:
            break
        parts.append(entry)
        total += len(entry)
    return "\n\n".join(parts)
