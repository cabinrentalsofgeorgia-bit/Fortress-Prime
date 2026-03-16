"""
VRS Infrastructure — Redis-backed async event bus for decoupled rule dispatch.

Exposes a module-level ``redis_client`` so consumers can import it directly
for BRPOP/LPUSH operations.  The client connects lazily on first await.

Uses Redis DB 1 with the fortress:events: prefix (DB 0 = cache, DB 1 = queues).
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from backend.core.config import settings

if TYPE_CHECKING:
    from backend.vrs.domain.automations import StreamlineEventPayload

logger = structlog.get_logger(service="vrs.event_bus")

EVENT_QUEUE_KEY = "fortress:events:streamline"
DLQ_KEY = "fortress:events:streamline:dlq"

# ---------------------------------------------------------------------------
# Lazy Redis client — initialized on first real call, importable everywhere
# ---------------------------------------------------------------------------

_client = None


def _events_redis_url() -> str:
    parts = settings.redis_url.rsplit("/", 1)
    return f"{parts[0]}/1" if len(parts) == 2 else f"{settings.redis_url}/1"


async def _ensure_client():
    import redis.asyncio as aioredis

    global _client
    if _client is None:
        _client = aioredis.from_url(
            _events_redis_url(),
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _client


class _LazyRedisClient:
    """Thin wrapper so ``redis_client`` can be imported at module level.

    Attribute access (``redis_client.brpop(...)``) lazily initialises the real
    aioredis client on the first awaited call, keeping module-level import
    side-effect-free.
    """

    async def brpop(self, *args, **kwargs):
        c = await _ensure_client()
        return await c.brpop(*args, **kwargs)

    async def lpush(self, *args, **kwargs):
        c = await _ensure_client()
        return await c.lpush(*args, **kwargs)

    async def llen(self, *args, **kwargs):
        c = await _ensure_client()
        return await c.llen(*args, **kwargs)

    async def aclose(self):
        c = await _ensure_client()
        await c.aclose()


redis_client = _LazyRedisClient()

# ---------------------------------------------------------------------------
# High-level helpers (kept for backward compat & convenience)
# ---------------------------------------------------------------------------


async def publish_vrs_event(event: "StreamlineEventPayload") -> bool:
    """Push a state-change event into the Redis queue. Returns True on success."""
    try:
        await redis_client.lpush(EVENT_QUEUE_KEY, event.model_dump_json())
        return True
    except Exception as exc:
        logger.warning("event_publish_failed", error=str(exc), entity=event.entity_type)
        return False


async def consume_one(timeout: int = 5) -> Optional["StreamlineEventPayload"]:
    """Block-pop one event from the queue. Returns None on timeout."""
    try:
        from backend.vrs.domain.automations import StreamlineEventPayload

        result = await redis_client.brpop(EVENT_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        _, payload_json = result
        return StreamlineEventPayload.model_validate_json(payload_json)
    except Exception as exc:
        logger.warning("event_consume_failed", error=str(exc))
        return None


async def send_to_dlq(raw_payload: str, error: str) -> None:
    """Push a failed event into the dead-letter queue for later inspection."""
    import json as _json

    envelope = _json.dumps({"payload": raw_payload, "error": error})
    try:
        await redis_client.lpush(DLQ_KEY, envelope)
    except Exception as exc:
        logger.error("dlq_push_failed", error=str(exc))


async def queue_depth() -> int:
    """Return the current number of pending events in the queue."""
    try:
        return await redis_client.llen(EVENT_QUEUE_KEY)
    except Exception:
        return -1


async def dlq_depth() -> int:
    """Return the current number of events in the dead-letter queue."""
    try:
        return await redis_client.llen(DLQ_KEY)
    except Exception:
        return -1


async def close() -> None:
    """Gracefully close the Redis connection."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
