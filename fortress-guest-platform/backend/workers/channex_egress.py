"""
Channex egress consumer — availability & rates push (deterministic, no LLM).

Subscribes to ``inventory.availability.changed``, rebuilds ~18 months of nightly
availability from PostgreSQL, POSTs a versioned JSON document to Channex (or proxy).

Run::

    python -m backend.workers.channex_egress

Environment
-----------
- ``KAFKA_BROKER_URL`` — Redpanda bootstrap (same as other workers).
- ``CHANNEX_EGRESS_TOPICS`` — default ``inventory.availability.changed``.
- ``CHANNEX_EGRESS_GROUP_ID`` — default ``fortress-channex-egress``.
- ``CHANNEX_EGRESS_AUTO_OFFSET_RESET`` — ``latest`` or ``earliest``.
- ``CHANNEX_API_BASE_URL`` — e.g. ``https://api.channex.io`` (empty disables HTTP push; offsets still commit).
- ``CHANNEX_API_KEY`` — Bearer token for outbound API calls.
- ``CHANNEX_AVAILABILITY_PATH`` — path appended to base, default ``/api/v1/channel/availability``.
  Use ``{listing_id}`` in the path if your upstream requires it per listing.

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
from backend.services.channex_calendar_export import (
    CHANNEX_LISTING_METADATA_KEY,
    build_channex_availability_document,
    push_url_for_listing,
)
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


def _availability_path_template() -> str:
    return (os.getenv("CHANNEX_AVAILABILITY_PATH") or "/api/v1/channel/availability").strip()


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

    async with AsyncSessionLocal() as session:
        document, skip_reason = await build_channex_availability_document(session, property_uuid)

    if skip_reason == "property_not_found":
        logger.warning("channex_egress_skip_property_not_found", property_id=str(property_uuid), offset=msg.offset)
        await _commit_kafka_offset(consumer, msg)
        return

    if skip_reason == "no_channex_listing_id":
        logger.warning(
            "channex_egress_skip_no_listing_mapping",
            property_id=str(property_uuid),
            ota_metadata_key=CHANNEX_LISTING_METADATA_KEY,
            offset=msg.offset,
        )
        await _commit_kafka_offset(consumer, msg)
        return

    assert document is not None

    base = _channex_base_url()
    if not base:
        logger.info(
            "channex_egress_push_disabled_no_base_url",
            property_id=str(property_uuid),
            listing_id=document.get("channex_listing_id"),
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

    listing_id = str(document.get("channex_listing_id") or "").strip()
    path_tpl = _availability_path_template()
    url = push_url_for_listing(base, path_tpl, listing_id)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    verify = _nemoclaw_style_verify_ssl(url)
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=verify) as client:
            await _post_document(client, url, headers, document)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if 400 <= status < 500:
            logger.error(
                "channex_egress_client_rejected",
                property_id=str(property_uuid),
                listing_id=listing_id,
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
        listing_id=listing_id,
        days=len(document.get("days") or []),
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
