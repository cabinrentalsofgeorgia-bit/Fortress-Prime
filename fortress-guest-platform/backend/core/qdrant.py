"""
Qdrant vector store initialization and client helpers for the FGP knowledge base.

Collection: fgp_knowledge
Embedding model: nomic-embed-text (768 dimensions) via local NIM on Nginx LB port 80
Distance metric: Cosine

This module is called at application startup to ensure the collection exists,
and provides reusable helpers for the vectorization worker.
"""

import structlog
import httpx

from backend.core.config import settings

logger = structlog.get_logger()

VECTOR_DIM = 768
DISTANCE_METRIC = "Cosine"
COLLECTION_NAME = settings.qdrant_collection_name  # "fgp_knowledge"


async def ensure_collection() -> bool:
    """Create the fgp_knowledge Qdrant collection if it does not already exist.

    Returns True if the collection is ready (existing or newly created).
    """
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{qdrant_url}/collections/{COLLECTION_NAME}",
                headers=headers,
            )
            if resp.status_code == 200:
                info = resp.json().get("result", {})
                logger.info(
                    "qdrant_collection_exists",
                    collection=COLLECTION_NAME,
                    points=info.get("points_count", 0),
                    status=info.get("status"),
                )
                return True
        except httpx.ConnectError:
            logger.warning("qdrant_unreachable", url=qdrant_url)
            return False

        try:
            create_resp = await client.put(
                f"{qdrant_url}/collections/{COLLECTION_NAME}",
                json={
                    "vectors": {
                        "size": VECTOR_DIM,
                        "distance": DISTANCE_METRIC,
                    },
                },
                headers=headers,
            )
            create_resp.raise_for_status()
            logger.info(
                "qdrant_collection_created",
                collection=COLLECTION_NAME,
                vector_dim=VECTOR_DIM,
                distance=DISTANCE_METRIC,
            )

            await client.put(
                f"{qdrant_url}/collections/{COLLECTION_NAME}/index",
                json={
                    "field_name": "source_table",
                    "field_schema": "keyword",
                },
                headers=headers,
            )
            await client.put(
                f"{qdrant_url}/collections/{COLLECTION_NAME}/index",
                json={
                    "field_name": "record_id",
                    "field_schema": "keyword",
                },
                headers=headers,
            )
            await client.put(
                f"{qdrant_url}/collections/{COLLECTION_NAME}/index",
                json={
                    "field_name": "property_id",
                    "field_schema": "keyword",
                },
                headers=headers,
            )

            return True

        except Exception as e:
            logger.error("qdrant_collection_create_failed", error=str(e))
            return False


async def ensure_payload_index(field_name: str, field_schema: str = "keyword") -> None:
    """Create a payload index on an existing collection (idempotent)."""
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.put(
                f"{qdrant_url}/collections/{COLLECTION_NAME}/index",
                json={"field_name": field_name, "field_schema": field_schema},
                headers=headers,
            )
    except Exception as e:
        logger.warning("qdrant_index_create_failed", field=field_name, error=str(e)[:200])


async def qdrant_health() -> dict:
    """Quick connectivity check for the health endpoint."""
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{qdrant_url}/collections/{COLLECTION_NAME}",
                headers=headers,
            )
            if resp.status_code == 200:
                info = resp.json().get("result", {})
                return {
                    "status": "connected",
                    "collection": COLLECTION_NAME,
                    "points": info.get("points_count", 0),
                }
            return {"status": "error", "code": resp.status_code}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:200]}
