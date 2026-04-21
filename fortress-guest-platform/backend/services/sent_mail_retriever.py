"""
SentMailRetriever — retrieves past Taylor sent-mail exemplars for composer injection.
====================================================================================
Clones the structure of knowledge_retriever.py. Queries two collections in
parallel and merges results:

  1. fgp_sent_mail       — tarball corpus (2022–2026, Taylor's guest replies)
  2. guest_golden_responses — curated exemplars (Gary-starred, quality_score=5)

Recency boost: final_score = cosine_score * (1 + RECENCY_COEFF * max(0, 1 - age/RECENCY_WINDOW_YEARS))
  Coefficient defaults to 0.15 over a 4-year window.
  Set RECENCY_COEFF = 0 to disable (corpus is already temporally tight at 2022+).

Timeout: 3s hard cap — this is on the critical path of draft generation.
Failure mode: returns [] on any Qdrant error; caller degrades to council-only composition.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import List, Optional

import httpx
import structlog

from backend.core.config import settings

logger = structlog.get_logger(service="sent_mail_retriever")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

QDRANT_URL = "http://127.0.0.1:6333"

COLLECTION_SENT_MAIL = "fgp_sent_mail"
COLLECTION_GOLDEN = "guest_golden_responses"

EMBED_MODEL = "nomic-embed-text"
VECTOR_DIM = 768
EMBED_TIMEOUT = 3.0  # fail-fast: retriever budget is tight
QDRANT_TIMEOUT = 3.0

# Recency boost — set to 0 to disable
RECENCY_COEFF = 0.15
RECENCY_WINDOW_SECONDS = 4.0 * 365.25 * 86400  # 4 years


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SentMailExemplar:
    subject: str
    body: str
    score: float
    sent_at: Optional[str]
    detected_topic: str
    source: str


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------

async def _embed(text: str) -> Optional[List[float]]:
    """Embed text via nomic-embed-text. Returns None on any failure."""
    # Try configured embed_base_url (spark-2) first; if unreachable the
    # 3s timeout fires and we fall back to spark-4.
    endpoints = [
        f"{settings.embed_base_url.rstrip('/')}/api/embeddings",
        "http://192.168.0.106:11434/api/embeddings",  # spark-4 fallback
    ]
    for url in endpoints:
        try:
            async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    json={"model": EMBED_MODEL, "prompt": text[:8000]},
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding", [])
                if len(vec) == VECTOR_DIM:
                    return vec
        except Exception as exc:
            logger.debug("embed_endpoint_failed", url=url, error=str(exc)[:80])
    logger.warning("sent_mail_retriever.embed_all_failed", text_len=len(text))
    return None


# ---------------------------------------------------------------------------
# Qdrant search helpers
# ---------------------------------------------------------------------------

async def _search_collection(
    collection: str,
    vector: List[float],
    limit: int,
) -> List[dict]:
    """Single-collection similarity search. Returns raw Qdrant result list."""
    try:
        async with httpx.AsyncClient(timeout=QDRANT_TIMEOUT) as client:
            resp = await client.post(
                f"{QDRANT_URL}/collections/{collection}/points/search",
                json={
                    "vector": vector,
                    "limit": limit,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            resp.raise_for_status()
            return resp.json().get("result", [])
    except Exception as exc:
        logger.warning(
            "sent_mail_retriever.collection_search_failed",
            collection=collection,
            error=str(exc)[:120],
        )
        return []


def _recency_boost(sent_at_epoch: Optional[int]) -> float:
    """Compute the recency multiplier for a point."""
    if not sent_at_epoch or RECENCY_COEFF == 0:
        return 1.0
    now = time.time()
    age_seconds = max(0.0, now - sent_at_epoch)
    weight = max(0.0, 1.0 - age_seconds / RECENCY_WINDOW_SECONDS)
    return 1.0 + RECENCY_COEFF * weight


def _point_to_exemplar(pt: dict, source_tag: str) -> Optional[SentMailExemplar]:
    """Convert a raw Qdrant point to a SentMailExemplar."""
    payload = pt.get("payload", {})
    score = float(pt.get("score", 0.0))

    if source_tag == COLLECTION_SENT_MAIL:
        body = payload.get("body", "").strip()
        subject = payload.get("subject", "")
        sent_at = payload.get("sent_at")
        sent_at_epoch = payload.get("sent_at_epoch")
        topic = payload.get("detected_topic", "other")
        source = payload.get("source", "fgp_sent_mail")
    else:
        # guest_golden_responses schema: ai_output, topic, cabin
        body = payload.get("ai_output", "").strip()
        topic_raw = payload.get("topic", "other")
        cabin = payload.get("cabin", "")
        subject = f"Guest reply — {cabin}" if cabin else "Guest reply"
        sent_at = None
        sent_at_epoch = None
        topic = topic_raw
        source = "guest_golden_responses"

    if not body:
        return None

    boosted_score = score * _recency_boost(sent_at_epoch)

    return SentMailExemplar(
        subject=subject,
        body=body,
        score=boosted_score,
        sent_at=sent_at,
        detected_topic=topic,
        source=source,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SentMailRetriever:
    """Retrieves past sent-mail exemplars for few-shot composer injection."""

    def __init__(self) -> None:
        pass

    async def find_similar_replies(
        self,
        inquiry_body: str,
        k: int = 3,
        min_score: float = 0.65,
    ) -> List[SentMailExemplar]:
        """
        Embed inquiry_body, query fgp_sent_mail and guest_golden_responses in
        parallel, merge, apply recency boost, filter by min_score, return top-k.

        Returns [] if inquiry_body is empty, Qdrant is unreachable, or no
        results exceed min_score.  Never raises — caller degrades gracefully.
        """
        if not inquiry_body or not inquiry_body.strip():
            return []

        try:
            vector = await _embed(inquiry_body.strip())
            if vector is None:
                return []

            # Query both collections concurrently; isolate failures per collection
            raw = await asyncio.gather(
                _search_collection(COLLECTION_SENT_MAIL, vector, k * 2),
                _search_collection(COLLECTION_GOLDEN, vector, k),
                return_exceptions=True,
            )
            sent_results: List[dict] = raw[0] if not isinstance(raw[0], BaseException) else []
            golden_results: List[dict] = raw[1] if not isinstance(raw[1], BaseException) else []
            if isinstance(raw[0], BaseException):
                logger.warning("sent_mail_search_error", error=str(raw[0])[:120])
            if isinstance(raw[1], BaseException):
                logger.warning("golden_search_error", error=str(raw[1])[:120])

            # Convert and merge
            candidates: List[SentMailExemplar] = []
            seen_bodies: set[str] = set()

            for pt in sent_results:
                ex = _point_to_exemplar(pt, COLLECTION_SENT_MAIL)
                if ex and ex.body not in seen_bodies:
                    candidates.append(ex)
                    seen_bodies.add(ex.body)

            for pt in golden_results:
                ex = _point_to_exemplar(pt, COLLECTION_GOLDEN)
                if ex and ex.body not in seen_bodies:
                    candidates.append(ex)
                    seen_bodies.add(ex.body)

            # Filter by min_score, sort by boosted score, return top-k
            filtered = [c for c in candidates if c.score >= min_score]
            filtered.sort(key=lambda x: x.score, reverse=True)
            top = filtered[:k]

            logger.info(
                "sent_mail_retriever.results",
                candidates=len(candidates),
                above_threshold=len(filtered),
                returned=len(top),
                top_score=round(top[0].score, 4) if top else 0,
                top_topics=[e.detected_topic for e in top],
            )
            return top

        except Exception as exc:
            logger.warning("sent_mail_retriever.find_failed", error=str(exc)[:200])
            return []
