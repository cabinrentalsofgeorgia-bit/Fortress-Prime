"""
Fortress event-bus consumer → Qdrant context → NemoClaw (Ray Serve) dispatch
===========================================================================
Subscribes to Redpanda/Kafka (``KAFKA_BROKER_URL``, default backplane listener),
runs a semantic retrieval pass against ``fgp_knowledge`` for the property
when an event carries ``property_id``, then POSTs an :class:`AgentDirective`-shaped
payload to the NemoClaw orchestrator (same path as ``POST /api/agent/dispatch``).

Run (from ``fortress-guest-platform`` with venv + env files loaded)::

    python -m backend.workers.event_consumer

Environment
-----------
- ``KAFKA_BROKER_URL`` — bootstrap (e.g. ``10.101.1.2:19092``).
- ``EVENT_CONSUMER_TOPICS`` — comma-separated topic list. Default includes
  ``trust.revenue.staged`` and ``reservation.confirmed`` (for future publishers).
- ``EVENT_CONSUMER_GROUP_ID`` — Kafka consumer group (default ``fortress-nemoclaw-consumers``).
- ``EVENT_CONSUMER_AUTO_OFFSET_RESET`` — ``latest`` or ``earliest``.
- ``EVENT_CONSUMER_DISPATCH_NEMOCLAW`` — ``1``/``true`` to call NemoClaw (default: true if
  ``nemoclaw_orchestrator_url`` is set).
- NemoClaw: ``nemoclaw_orchestrator_url``, ``nemoclaw_orchestrator_api_key`` (see ``Settings``).
- Qdrant + embeddings: ``qdrant_url``, ``embed_base_url``, ``embed_model`` (see ``vector_db``).

SSL verification toward NemoClaw follows ``NEMOCLAW_ORCHESTRATOR_VERIFY_SSL`` (see ``api/agent.py``).

Kafka commits
-------------
``enable_auto_commit=False``. Offsets commit only after NemoClaw HTTP success (when enabled) and
``ai_insights`` UPSERT. Any unhandled failure stops the process without committing so the message
is redelivered after restart.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import signal
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from qdrant_client.http import models as qmodels
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.core.event_publisher import REDPANDA_BROKER
from backend.core.qdrant import COLLECTION_NAME
from backend.core.vector_db import embed_text_sync, get_qdrant_client
from backend.models.ai_insight import AiInsight

logger = structlog.get_logger(service="event_consumer")
_stdlib_log = logging.getLogger(__name__)


class NemoclawDispatchError(Exception):
    """Transient 5xx from the Ray Serve / NemoClaw HTTP surface."""

    pass

DEFAULT_TOPICS: tuple[str, ...] = (
    "trust.revenue.staged",
    "reservation.confirmed",
)


def _parse_topics(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return list(DEFAULT_TOPICS)
    return [t.strip() for t in raw.split(",") if t.strip()]


def _auto_offset() -> str:
    v = (os.getenv("EVENT_CONSUMER_AUTO_OFFSET_RESET") or "latest").strip().lower()
    return v if v in {"latest", "earliest"} else "latest"


def _group_id() -> str:
    return (os.getenv("EVENT_CONSUMER_GROUP_ID") or "fortress-nemoclaw-consumers").strip()


def _dispatch_nemoclaw_enabled() -> bool:
    explicit = (os.getenv("EVENT_CONSUMER_DISPATCH_NEMOCLAW") or "").strip().lower()
    if explicit in {"0", "false", "no", "off"}:
        return False
    if explicit in {"1", "true", "yes", "on"}:
        return True
    return bool(str(settings.nemoclaw_orchestrator_url or "").strip())


def _nemoclaw_execute_url() -> str:
    base = str(settings.nemoclaw_orchestrator_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("nemoclaw_orchestrator_url is not configured")
    return f"{base}/api/agent/execute"


def _nemoclaw_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = str(settings.nemoclaw_orchestrator_api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    return headers


def _reference_id_from_event(payload: dict[str, Any]) -> str:
    for key in ("confirmation_code", "property_id", "reservation_id"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()[:255]
    return "unknown"


def _insight_payload_from_nemoclaw(body: dict[str, Any]) -> dict[str, Any]:
    rp = body.get("result_payload")
    return dict(rp) if isinstance(rp, dict) else {}


async def _commit_kafka_offset(consumer: AIOKafkaConsumer, msg: Any) -> None:
    tp = TopicPartition(msg.topic, msg.partition)
    await consumer.commit({tp: OffsetAndMetadata(msg.offset + 1, "")})


async def _persist_ai_insight(
    *,
    task_id: str,
    event_type: str,
    reference_id: str,
    nemoclaw_body: dict[str, Any],
) -> None:
    insight_payload = _insight_payload_from_nemoclaw(nemoclaw_body)
    stmt = pg_insert(AiInsight).values(
        id=uuid.uuid4(),
        task_id=task_id.strip()[:255],
        event_type=event_type.strip()[:128],
        reference_id=reference_id.strip()[:255],
        insight_payload=insight_payload,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ai_insights_task_id",
        set_={
            "insight_payload": stmt.excluded.insight_payload,
            "event_type": stmt.excluded.event_type,
            "reference_id": stmt.excluded.reference_id,
        },
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()


def _nemoclaw_verify_ssl(base_url: str) -> bool:
    override = (os.getenv("NEMOCLAW_ORCHESTRATOR_VERIFY_SSL") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    host = (urlsplit(base_url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


def _extract_property_id(payload: dict[str, Any]) -> str | None:
    for key in ("property_id", "property_uuid", "sovereign_property_id"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _extract_confirmation(payload: dict[str, Any]) -> str | None:
    val = payload.get("confirmation_code")
    if val is not None and str(val).strip():
        return str(val).strip()
    return None


def _qdrant_snippets_sync(property_id: str | None, confirmation_code: str | None) -> list[str]:
    """Retrieve short text snippets from fgp_knowledge; best-effort only."""
    query_bits = [
        "cabin guest welcome concierge house rules policies amenities access WiFi parking",
    ]
    if confirmation_code:
        query_bits.append(f"reservation confirmation {confirmation_code}")
    if property_id:
        query_bits.append(f"property {property_id}")
    query_text = " ".join(query_bits)

    try:
        vector = embed_text_sync(query_text)
    except Exception as exc:
        logger.warning("event_consumer_embed_failed", error=str(exc)[:200])
        return []

    client = get_qdrant_client()
    flt: qmodels.Filter | None = None
    if property_id:
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="record_id",
                    match=qmodels.MatchValue(value=property_id),
                ),
            ],
        )

    try:
        resp = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=8,
            query_filter=flt,
            with_payload=True,
        )
        hits = list(resp.points)
    except Exception as exc:
        logger.warning("event_consumer_qdrant_search_failed", error=str(exc)[:200])
        return []

    snippets: list[str] = []
    for h in hits:
        pl = (getattr(h, "payload", None) or {}) if h is not None else {}
        text = pl.get("text")
        if isinstance(text, str) and text.strip():
            snippets.append(text.strip()[:1200])
        elif isinstance(pl.get("name"), str):
            snippets.append(str(pl.get("name"))[:200])

    if not snippets and flt is not None:
        try:
            resp2 = client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=6,
                with_payload=True,
            )
            hits2 = list(resp2.points)
        except Exception as exc:
            logger.warning("event_consumer_qdrant_fallback_failed", error=str(exc)[:200])
            return []
        for h in hits2:
            pl = (getattr(h, "payload", None) or {}) if h is not None else {}
            text = pl.get("text")
            if isinstance(text, str) and text.strip():
                snippets.append(text.strip()[:1200])

    return snippets[:12]


def _build_directive(
    *,
    topic: str,
    partition: int,
    offset: int,
    key: bytes | None,
    payload: dict[str, Any],
    qdrant_snippets: list[str],
) -> dict[str, Any]:
    # Stable per Kafka record so redelivery + ai_insights UPSERT stay idempotent.
    task_id = f"evt-{topic}-{partition}-{offset}"
    key_hint = key.decode("utf-8", errors="replace") if key else ""
    property_id = _extract_property_id(payload)
    confirmation = _extract_confirmation(payload)

    return {
        "task_id": task_id,
        "intent": "guest_concierge",
        "context_payload": {
            "source": "kafka_event_consumer",
            "kafka_topic": topic,
            "kafka_partition": partition,
            "kafka_offset": offset,
            "kafka_key": key_hint,
            "property_id": property_id,
            "confirmation_code": confirmation,
            "reservation": payload,
            "snippets": qdrant_snippets,
            "qdrant_collection": COLLECTION_NAME,
        },
    }


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=30),
    retry=retry_if_exception_type(NemoclawDispatchError),
    before_sleep=before_sleep_log(_stdlib_log, logging.WARNING),
    reraise=True,
)
async def _dispatch_to_nemoclaw_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(url, json=payload, headers=headers)
    if response.status_code in (500, 502, 503, 504):
        raise NemoclawDispatchError(f"Ray Serve transient error: {response.status_code}")
    response.raise_for_status()
    if not response.content.strip():
        return {}
    try:
        body = response.json()
    except json.JSONDecodeError:
        return {"_non_json_body": response.text[:800]}
    return body if isinstance(body, dict) else {"_parsed": body}


async def _dispatch_nemoclaw(directive: dict[str, Any]) -> dict[str, Any]:
    url = _nemoclaw_execute_url()
    verify = _nemoclaw_verify_ssl(url)
    headers = _nemoclaw_headers()
    async with httpx.AsyncClient(timeout=120.0, verify=verify) as client:
        body = await _dispatch_to_nemoclaw_with_retry(client, url, headers, directive)
    logger.info(
        "event_consumer_nemoclaw_ok",
        task_id=directive.get("task_id"),
        nemoclaw_status=body.get("status") if isinstance(body, dict) else None,
    )
    return body


async def handle_record(consumer: AIOKafkaConsumer, msg: Any) -> None:
    value = msg.value
    topic = msg.topic
    partition = msg.partition
    offset = msg.offset
    key = msg.key

    property_id = _extract_property_id(value)
    confirmation = _extract_confirmation(value)

    snippets = await asyncio.to_thread(
        _qdrant_snippets_sync,
        property_id,
        confirmation,
    )

    directive = _build_directive(
        topic=topic,
        partition=partition,
        offset=offset,
        key=key,
        payload=value,
        qdrant_snippets=snippets,
    )

    logger.info(
        "event_consumer_processed",
        topic=topic,
        partition=partition,
        offset=offset,
        property_id=property_id,
        confirmation_code=confirmation,
        qdrant_hits=len(snippets),
        task_id=directive["task_id"],
    )

    if not _dispatch_nemoclaw_enabled():
        logger.info("event_consumer_nemoclaw_skipped", task_id=directive["task_id"])
        await _commit_kafka_offset(consumer, msg)
        return

    nemoclaw_body = await _dispatch_nemoclaw(directive)
    await _persist_ai_insight(
        task_id=str(directive["task_id"]),
        event_type=topic,
        reference_id=_reference_id_from_event(value),
        nemoclaw_body=nemoclaw_body,
    )
    await _commit_kafka_offset(consumer, msg)
    logger.info(
        "event_consumer_kafka_committed",
        topic=topic,
        partition=partition,
        offset=offset,
        task_id=directive["task_id"],
    )


async def run_consumer_loop(stop: asyncio.Event) -> None:
    bootstrap = (os.getenv("KAFKA_BROKER_URL") or REDPANDA_BROKER).strip()
    if not bootstrap:
        raise RuntimeError("KAFKA_BROKER_URL is not set (and no default broker configured)")

    topics = _parse_topics(os.getenv("EVENT_CONSUMER_TOPICS"))
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        group_id=_group_id(),
        enable_auto_commit=False,
        auto_offset_reset=_auto_offset(),
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    await consumer.start()
    logger.info(
        "event_consumer_started",
        bootstrap=bootstrap,
        topics=topics,
        group_id=_group_id(),
        auto_offset_reset=_auto_offset(),
    )
    try:
        while not stop.is_set():
            try:
                result = await consumer.getmany(timeout_ms=1000, max_records=16)
            except KafkaError as exc:
                logger.warning("event_consumer_poll_error", error=str(exc)[:200])
                await asyncio.sleep(1.0)
                continue

            if not result:
                await asyncio.sleep(0.05)
                continue

            for tp, batch in result.items():
                for msg in batch:
                    if not isinstance(msg.value, dict):
                        logger.warning(
                            "event_consumer_skip_non_object",
                            topic=msg.topic,
                            offset=msg.offset,
                        )
                        await _commit_kafka_offset(consumer, msg)
                        continue
                    await handle_record(consumer, msg)
    finally:
        await consumer.stop()
        logger.info("event_consumer_stopped")


async def main() -> None:
    stop = asyncio.Event()

    def _shutdown() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            break

    await run_consumer_loop(stop)


if __name__ == "__main__":
    asyncio.run(main())
