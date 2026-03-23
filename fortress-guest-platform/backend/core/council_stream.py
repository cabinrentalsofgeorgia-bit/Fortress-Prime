"""
Redis-backed council streaming helpers.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from backend.core.config import settings

TERMINAL_EVENT_TYPES = {"done", "error"}


def council_channel(job_id: str) -> str:
    return f"council_stream:{job_id}"


def council_replay_key(job_id: str) -> str:
    return f"council_replay:{job_id}"


def council_state_key(job_id: str) -> str:
    return f"council_state:{job_id}"


def _serialize_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=True, default=str, separators=(",", ":"))


def _deserialize_event(payload: str) -> dict[str, Any]:
    return json.loads(payload)


async def create_council_redis() -> aioredis.Redis:
    return aioredis.from_url(
        settings.arq_redis_url,
        decode_responses=True,
        socket_timeout=15,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


async def publish_council_event(
    redis: aioredis.Redis,
    job_id: str,
    event: dict[str, Any],
) -> str:
    payload = _serialize_event(event)
    stream_id = await redis.xadd(
        council_replay_key(job_id),
        {"event": payload},
        maxlen=settings.council_stream_maxlen,
        approximate=True,
    )
    envelope = _serialize_event({"stream_id": stream_id, "event": event})
    await redis.publish(council_channel(job_id), envelope)
    state_payload = _serialize_event(
        {
            "job_id": job_id,
            "last_event_id": stream_id,
            "event_type": event.get("type"),
            "event": event,
        }
    )
    ttl = settings.council_stream_ttl_seconds
    await redis.set(council_state_key(job_id), state_payload, ex=ttl)
    await redis.expire(council_replay_key(job_id), ttl)
    return stream_id


async def replay_council_events(
    redis: aioredis.Redis,
    job_id: str,
    *,
    after_id: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    min_id = "-" if not after_id else f"({after_id}"
    rows = await redis.xrange(council_replay_key(job_id), min=min_id, max="+")
    replay: list[tuple[str, dict[str, Any]]] = []
    for stream_id, fields in rows:
        payload = fields.get("event")
        if not payload:
            continue
        replay.append((stream_id, _deserialize_event(payload)))
    return replay


async def get_council_state(redis: aioredis.Redis, job_id: str) -> dict[str, Any] | None:
    payload = await redis.get(council_state_key(job_id))
    if not payload:
        return None
    return _deserialize_event(payload)


def is_terminal_event(event: dict[str, Any]) -> bool:
    return str(event.get("type") or "").lower() in TERMINAL_EVENT_TYPES
