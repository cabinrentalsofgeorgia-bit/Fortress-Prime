"""
Channex egress consumer — ARI availability & restrictions push.

Subscribes to ``inventory.availability.changed``, rebuilds ~18 months of nightly
availability from PostgreSQL, and pushes:
- Room Type availability to `/api/v1/availability`
- Rate Plan restrictions / rates to `/api/v1/restrictions`

Run::

    python -m backend.workers.channex_egress

Environment
-----------
- ``KAFKA_BROKER_URL`` — Redpanda bootstrap (same as other workers).
- ``CHANNEX_EGRESS_TOPICS`` — default ``inventory.availability.changed``.
- ``CHANNEX_EGRESS_GROUP_ID`` — default ``fortress-channex-egress``.
- ``CHANNEX_EGRESS_AUTO_OFFSET_RESET`` — ``latest`` or ``earliest``.
- ``CHANNEX_API_BASE_URL`` — e.g. ``https://api.channex.io`` (empty disables HTTP push; offsets still commit).
- ``CHANNEX_API_KEY`` — API key for outbound API calls.

Kafka commits
-------------
``enable_auto_commit=False``. Offset commits only after a successful HTTP push **or** a deterministic
skip (unknown property, missing Channex listing id, push disabled). Transient 5xx / network errors
retry with tenacity; after exhaustion the process exits without committing so the message is redelivered.

systemd (example)::

    [Service]
    WorkingDirectory=/home/admin/Fortress-Prime/fortress-guest-platform
    EnvironmentFile=/home/admin/Fortress-Prime/fortress-guest-platform/.env.dgx
    ExecStart=/path/to/venv/bin/python -m backend.workers.channex_egress
"""

from __future__ import annotations

import asyncio
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
from backend.models.property import Property
from backend.services.channex_calendar_export import (
    CHANNEX_LISTING_METADATA_KEY,
    channex_listing_id_for_property,
)
from backend.services.channex_ari import build_channex_ari_payloads, fetch_channex_catalog
from backend.services.inventory_events import TOPIC_INVENTORY_AVAILABILITY_CHANGED

logger = structlog.get_logger(service="channex_egress")
_stdlib_log = logging.getLogger(__name__)


class ChannexPushTransientError(Exception):
    """Retryable HTTP / transport failure when pushing availability to Channex."""


def _parse_topics(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return [TOPIC_INVENTORY_AVAILABILITY_CHANGED]
    return [t.strip() for t in raw.split(",") if t.strip()]


def _group_id() -> str:
    return (os.getenv("CHANNEX_EGRESS_GROUP_ID") or "fortress-channex-egress").strip()


def _auto_offset() -> str:
    v = (os.getenv("CHANNEX_EGRESS_AUTO_OFFSET_RESET") or "latest").strip().lower()
    return v if v in {"latest", "earliest"} else "latest"


def _channex_base_url() -> str:
    return str(settings.channex_api_base_url or "").strip()


def _channex_api_key() -> str:
    return str(settings.channex_api_key or "").strip()


def _channex_api_base() -> str:
    base = _channex_base_url().strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api/v1"):
        return base
    if base.endswith("/api"):
        return f"{base}/v1"
    return f"{base}/api/v1"


def _nemoclaw_style_verify_ssl(url: str) -> bool:
    """Match private-LAN TLS behavior used for NemoClaw outbound calls."""
    override = (os.getenv("CHANNEX_EGRESS_VERIFY_SSL") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    host = (urlsplit(url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        import ipaddress

        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


async def _commit_kafka_offset(consumer: AIOKafkaConsumer, msg: Any) -> None:
    tp = TopicPartition(msg.topic, msg.partition)
    await consumer.commit({tp: OffsetAndMetadata(msg.offset + 1, "")})


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential_jitter(initial=1, max=120),
    retry=retry_if_exception_type(ChannexPushTransientError),
    before_sleep=before_sleep_log(_stdlib_log, logging.WARNING),
    reraise=True,
)
async def _post_document(client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any]) -> None:
    try:
        response = await client.post(url, json=body, headers=headers)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
        raise ChannexPushTransientError(str(exc)[:300]) from exc

    if response.status_code in (429, 500, 502, 503, 504):
        raise ChannexPushTransientError(f"HTTP {response.status_code}: {response.text[:240]}")
    response.raise_for_status()


async def handle_message(consumer: AIOKafkaConsumer, msg: Any) -> None:
    value = msg.value
    if not isinstance(value, dict):
        logger.warning("channex_egress_skip_non_object", topic=msg.topic, offset=msg.offset)
        await _commit_kafka_offset(consumer, msg)
        return

    raw_pid = value.get("property_id")
    if raw_pid is None or not str(raw_pid).strip():
        logger.warning("channex_egress_skip_missing_property_id", offset=msg.offset)
        await _commit_kafka_offset(consumer, msg)
        return

    try:
        property_uuid = uuid.UUID(str(raw_pid).strip())
    except ValueError:
        logger.warning("channex_egress_skip_bad_property_id", property_id=raw_pid, offset=msg.offset)
        await _commit_kafka_offset(consumer, msg)
        return

    base = _channex_base_url()
    if not base:
        logger.info(
            "channex_egress_push_disabled_no_base_url",
            property_id=str(property_uuid),
        )
        await _commit_kafka_offset(consumer, msg)
        return

    api_key = _channex_api_key()
    if not api_key:
        logger.error(
            "channex_egress_missing_api_key",
            property_id=str(property_uuid),
            kafka_offset=msg.offset,
            note="offset not committed; set CHANNEX_API_KEY or clear CHANNEX_API_BASE_URL",
        )
        await asyncio.sleep(15.0)
        return

    api_base = _channex_api_base()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "user-api-key": api_key,
    }

    verify = _nemoclaw_style_verify_ssl(api_base)
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=verify) as client:
            async with AsyncSessionLocal() as session:
                prop = await session.get(Property, property_uuid)
                if prop is None:
                    logger.warning(
                        "channex_egress_skip_property_not_found",
                        property_id=str(property_uuid),
                        kafka_offset=msg.offset,
                    )
                    await _commit_kafka_offset(consumer, msg)
                    return
                listing_id = channex_listing_id_for_property(prop)
                if not listing_id:
                    logger.warning(
                        "channex_egress_skip_no_listing_mapping",
                        property_id=str(property_uuid),
                        ota_metadata_key=CHANNEX_LISTING_METADATA_KEY,
                        kafka_offset=msg.offset,
                    )
                    await _commit_kafka_offset(consumer, msg)
                    return

                room_type, rate_plan = await fetch_channex_catalog(
                    client=client,
                    api_base=api_base,
                    headers=headers,
                    property_id=listing_id,
                )
                if room_type is None or rate_plan is None:
                    logger.warning(
                        "channex_egress_skip_missing_catalog",
                        property_id=str(property_uuid),
                        listing_id=listing_id,
                        room_type_present=room_type is not None,
                        rate_plan_present=rate_plan is not None,
                        kafka_offset=msg.offset,
                    )
                    await _commit_kafka_offset(consumer, msg)
                    return
                availability_body, restrictions_body = await build_channex_ari_payloads(
                    session,
                    property_uuid,
                    room_type_id=str(room_type.get("id")),
                    rate_plan_id=str(rate_plan.get("id")),
                )
            await _post_document(client, f"{api_base}/availability", headers, availability_body)
            await _post_document(client, f"{api_base}/restrictions", headers, restrictions_body)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if 400 <= status < 500:
            logger.error(
                "channex_egress_client_rejected",
                property_id=str(property_uuid),
                listing_id=listing_id if "listing_id" in locals() else None,
                status_code=status,
                detail=exc.response.text[:500],
                kafka_offset=msg.offset,
            )
            await _commit_kafka_offset(consumer, msg)
            return
        raise

    logger.info(
        "channex_egress_push_ok",
        property_id=str(property_uuid),
        listing_id=listing_id if "listing_id" in locals() else None,
        room_type_id=str(room_type.get("id")) if "room_type" in locals() and room_type else None,
        rate_plan_id=str(rate_plan.get("id")) if "rate_plan" in locals() and rate_plan else None,
        kafka_offset=msg.offset,
    )
    await _commit_kafka_offset(consumer, msg)


async def run_consumer_loop(stop: asyncio.Event) -> None:
    bootstrap = (os.getenv("KAFKA_BROKER_URL") or REDPANDA_BROKER).strip()
    if not bootstrap:
        raise RuntimeError("KAFKA_BROKER_URL is not set (and no default broker configured)")

    topics = _parse_topics(os.getenv("CHANNEX_EGRESS_TOPICS"))
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
        "channex_egress_started",
        bootstrap=bootstrap,
        topics=topics,
        group_id=_group_id(),
        auto_offset_reset=_auto_offset(),
    )
    try:
        while not stop.is_set():
            try:
                result = await consumer.getmany(timeout_ms=1000, max_records=8)
            except KafkaError as exc:
                logger.warning("channex_egress_poll_error", error=str(exc)[:200])
                await asyncio.sleep(1.0)
                continue

            if not result:
                await asyncio.sleep(0.05)
                continue

            for _tp, batch in result.items():
                for msg in batch:
                    await handle_message(consumer, msg)
    finally:
        await consumer.stop()
        logger.info("channex_egress_stopped")


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
