"""
Revenue Consumer — Iron Dome journal posting from ``trust.revenue.staged``.

Consumes Kafka/Redpanda messages published by ``POST /api/admin/reconcile-revenue``
and reservation webhooks, then writes balanced ``journal_entries`` +
``journal_line_items`` rows (DR Cash 1010, CR Owner Trust 2000, CR PM Revenue 4100).

Run (from ``fortress-guest-platform``)::

    python -m backend.workers.revenue_consumer

Environment
-----------
- ``KAFKA_BROKER_URL`` — bootstrap servers (default matches ``EventPublisher``).
- ``REVENUE_CONSUMER_GROUP_ID`` — default ``fortress-revenue-consumer``.
- ``REVENUE_CONSUMER_TOPIC`` — default ``trust.revenue.staged``.
- ``REVENUE_CONSUMER_AUTO_OFFSET_RESET`` — ``earliest`` or ``latest`` (default ``earliest``).
- ``REVENUE_DEFAULT_PM_PCT`` — when ``management_splits`` has no row for the unit (default ``35``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal
from backend.core.event_publisher import REDPANDA_BROKER

logger = structlog.get_logger(service="revenue_consumer")
_stdlib_log = logging.getLogger(__name__)

TOPIC_DEFAULT = "trust.revenue.staged"


def _bootstrap() -> str:
    return (os.getenv("KAFKA_BROKER_URL") or REDPANDA_BROKER).strip()


def _group_id() -> str:
    return (os.getenv("REVENUE_CONSUMER_GROUP_ID") or "fortress-revenue-consumer").strip()


def _topic() -> str:
    return (os.getenv("REVENUE_CONSUMER_TOPIC") or TOPIC_DEFAULT).strip()


def _auto_offset() -> str:
    v = (os.getenv("REVENUE_CONSUMER_AUTO_OFFSET_RESET") or "earliest").strip().lower()
    return v if v in {"latest", "earliest"} else "earliest"


def _default_pm_pct() -> float:
    raw = (os.getenv("REVENUE_DEFAULT_PM_PCT") or "35").strip()
    try:
        v = float(raw)
        return max(0.0, min(100.0, v))
    except ValueError:
        return 35.0


async def _already_journaled(db: AsyncSession, confirmation_code: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1 FROM journal_entries
            WHERE reference_id = :code
              AND reference_type = 'reservation_revenue'
            LIMIT 1
            """
        ),
        {"code": confirmation_code},
    )
    return result.first() is not None


async def _resolve_split(db: AsyncSession, streamline_unit_id: str) -> tuple[float, float]:
    """Return (owner_pct, pm_pct) summing to 100."""
    row = (
        await db.execute(
            text(
                """
                SELECT owner_pct, pm_pct
                FROM management_splits
                WHERE property_id = :pid
                LIMIT 1
                """
            ),
            {"pid": streamline_unit_id},
        )
    ).first()
    if row is not None:
        owner = float(row.owner_pct or 0)
        pm = float(row.pm_pct or 0)
        if owner > 0 or pm > 0:
            s = owner + pm
            if s > 0 and abs(s - 100.0) > 0.01:
                owner = round(100.0 * owner / s, 2)
                pm = round(100.0 - owner, 2)
            return owner, pm
    pm = _default_pm_pct()
    return round(100.0 - pm, 2), pm


async def process_revenue_payload(db: AsyncSession, payload: dict[str, Any]) -> bool:
    """
    Insert one balanced journal entry for ``trust.revenue.staged`` payload.

    Returns True if a row was written or idempotently skipped; False to retry.
    """
    code = str(payload.get("confirmation_code") or "").strip()
    unit_id = str(payload.get("property_id") or "").strip()
    try:
        total = float(payload.get("total_amount") or 0)
    except (TypeError, ValueError):
        total = 0.0

    if not code or not unit_id or total <= 0:
        logger.warning("revenue_payload_invalid", payload=payload)
        return True

    if await _already_journaled(db, code):
        logger.info("revenue_already_journaled", confirmation_code=code)
        return True

    owner_pct, pm_pct = await _resolve_split(db, unit_id)
    total_d = Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    pm_amt = (total_d * Decimal(str(pm_pct)) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    owner_amt = (total_d - pm_amt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    desc = f"Reservation revenue — {code} (owner {owner_pct:.0f}% / PM {pm_pct:.0f}%)"

    je_row = await db.execute(
        text(
            """
            INSERT INTO journal_entries
                (property_id, entry_date, description, reference_type, reference_id)
            VALUES (:pid, CURRENT_DATE, :desc, 'reservation_revenue', :ref)
            RETURNING id
            """
        ),
        {"pid": unit_id, "desc": desc, "ref": code},
    )
    je_id = je_row.scalar()

    amt_float = float(total_d)
    o_float = float(owner_amt)
    p_float = float(pm_amt)

    await db.execute(
        text(
            """
            INSERT INTO journal_line_items (journal_entry_id, account_id, debit, credit)
            VALUES
                (:je, (SELECT id FROM accounts WHERE code = '1010'), :cash, 0),
                (:je, (SELECT id FROM accounts WHERE code = '2000'), 0, :owner),
                (:je, (SELECT id FROM accounts WHERE code = '4100'), 0, :pm)
            """
        ),
        {"je": je_id, "cash": amt_float, "owner": o_float, "pm": p_float},
    )
    await db.commit()
    logger.info(
        "revenue_journaled",
        confirmation_code=code,
        journal_entry_id=str(je_id),
        total=amt_float,
        owner_liability=o_float,
        pm_revenue=p_float,
        unit_id=unit_id,
    )
    return True


async def _commit_offset(consumer: AIOKafkaConsumer, msg: Any) -> None:
    tp = TopicPartition(msg.topic, msg.partition)
    await consumer.commit({tp: OffsetAndMetadata(msg.offset + 1, "")})


async def handle_message(consumer: AIOKafkaConsumer, msg: Any) -> None:
    tp = msg.topic
    offset = msg.offset
    try:
        payload = msg.value if isinstance(msg.value, dict) else json.loads(msg.value.decode("utf-8"))
    except Exception as exc:
        logger.error("revenue_bad_json", error=str(exc)[:200], topic=tp, offset=offset)
        await _commit_offset(consumer, msg)
        return

    try:
        async with AsyncSessionLocal() as db:
            try:
                ok = await process_revenue_payload(db, payload)
            except Exception as exc:
                await db.rollback()
                logger.exception("revenue_process_failed", error=str(exc)[:500])
                return
    except Exception:
        logger.exception("revenue_session_failed")
        return

    if ok:
        await _commit_offset(consumer, msg)


async def run_consumer_loop(stop: asyncio.Event) -> None:
    bootstrap = _bootstrap()
    if not bootstrap:
        raise RuntimeError("KAFKA_BROKER_URL is not set")

    topic = _topic()
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=_group_id(),
        enable_auto_commit=False,
        auto_offset_reset=_auto_offset(),
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )
    await consumer.start()
    logger.info(
        "revenue_consumer_started",
        bootstrap=bootstrap,
        topic=topic,
        group_id=_group_id(),
        auto_offset_reset=_auto_offset(),
    )
    try:
        while not stop.is_set():
            try:
                result = await consumer.getmany(timeout_ms=1000, max_records=16)
            except KafkaError as exc:
                logger.warning("revenue_poll_error", error=str(exc)[:200])
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
        logger.info("revenue_consumer_stopped")


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
