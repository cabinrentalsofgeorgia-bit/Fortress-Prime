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
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import signal
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from qdrant_client.http import models as qmodels

from backend.core.config import settings
from backend.core.event_publisher import REDPANDA_BROKER
from backend.core.qdrant import COLLECTION_NAME
from backend.core.vector_db import embed_text_sync, get_qdrant_client

logger = structlog.get_logger(service="event_consumer")

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
    task_id = f"evt-{topic}-{partition}-{offset}-{uuid.uuid4().hex[:8]}"
    key_hint = key.decode("utf-8", errors="replace") if key else ""
    property_id = _extract_property_id(payload)
    confirmation = _extract_confirmation(payload)

    intent = (
        "You are the sovereign concierge brain for Cabin Rentals of Georgia. "
        "Using ONLY the context provided (event payload + knowledge snippets), "
        "produce a concise welcome and pre-arrival brief for staff to send or adapt. "
        "Include: tone (warm, premium), check-in reminders if dates are present, "
        "and any property-specific rules from snippets. "
        "Do not invent policies, fees, or amenities not supported by the context. "
        "Output plain text suitable for email or SMS follow-up — no JSON, no markdown headings."
    )

    return {
        "task_id": task_id,
        "intent": intent,
        "context_payload": {
            "source": "kafka_event_consumer",
            "kafka_topic": topic,
            "kafka_partition": partition,
            "kafka_offset": offset,
            "kafka_key": key_hint,
            "property_id": property_id,
            "confirmation_code": confirmation,
            "event_payload": payload,
            "qdrant_snippets": qdrant_snippets,
            "qdrant_collection": COLLECTION_NAME,
        },
    }


async def _dispatch_nemoclaw(directive: dict[str, Any]) -> None:
    url = _nemoclaw_execute_url()
    verify = _nemoclaw_verify_ssl(url)
    async with httpx.AsyncClient(timeout=120.0, verify=verify) as client:
        resp = await client.post(url, json=directive, headers=_nemoclaw_headers())
        resp.raise_for_status()
    logger.info(
        "event_consumer_nemoclaw_ok",
        task_id=directive.get("task_id"),
        status_code=resp.status_code,
    )


async def handle_record(
    *,
    topic: str,
    partition: int,
    offset: int,
    key: bytes | None,
    value: dict[str, Any],
) -> None:
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
        return

    try:
        await _dispatch_nemoclaw(directive)
    except Exception as exc:
        logger.error(
            "event_consumer_nemoclaw_failed",
            task_id=directive["task_id"],
            error=str(exc)[:400],
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
        enable_auto_commit=True,
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
                    try:
                        if not isinstance(msg.value, dict):
                            logger.warning(
                                "event_consumer_skip_non_object",
                                topic=msg.topic,
                                offset=msg.offset,
                            )
                            continue
                        await handle_record(
                            topic=msg.topic,
                            partition=msg.partition,
                            offset=msg.offset,
                            key=msg.key,
                            value=msg.value,
                        )
                    except Exception:
                        logger.exception(
                            "event_consumer_message_failed",
                            topic=getattr(msg, "topic", ""),
                            offset=getattr(msg, "offset", -1),
                        )
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
