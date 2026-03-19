#!/usr/bin/env python3
"""
SMS Dispatch Worker — Sovereign Twilio Pipeline (Godhead Strangler Pattern)
===========================================================================
Polls the scheduled_messages table for pending outbound SMS, fires them
through the existing TwilioClient, and persists delivery outcomes in the
messages table — all against the local fortress_guest Postgres database.

Designed to run as a standalone daemon on the DGX node:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.workers.sms_dispatch

Or imported as an async task in the FastAPI lifespan:
  from backend.workers.sms_dispatch import SmsDispatchWorker
  worker = SmsDispatchWorker()
  asyncio.create_task(worker.run_loop())

Data flow:
  scheduled_messages (status=pending, scheduled_for<=now)
    → TwilioClient.send_sms()
    → messages row persisted via MessageService
    → scheduled_messages row stamped sent/failed

All guest data stays on sovereign hardware. No PII leaves the cluster.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import select, and_

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.integrations.twilio_client import TwilioClient
from backend.models.message import ScheduledMessage

logger = structlog.get_logger(service="sms_dispatch_worker")

DEFAULT_POLL_INTERVAL = 30
BATCH_SIZE = 20
MAX_RETRIES_PER_MESSAGE = 3


class SmsDispatchWorker:
    """Fault-tolerant SMS dispatch loop with structured logging."""

    def __init__(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        batch_size: int = BATCH_SIZE,
    ):
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._running = False
        self._twilio = TwilioClient()
        self._cycle_count = 0

    async def dispatch_batch(self) -> dict:
        """Drain one batch of pending scheduled messages.

        Returns a summary dict with counts of sent, failed, and skipped.
        """
        summary = {"sent": 0, "failed": 0, "skipped": 0}
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledMessage)
                .where(
                    and_(
                        ScheduledMessage.status == "pending",
                        ScheduledMessage.scheduled_for <= now,
                    )
                )
                .order_by(ScheduledMessage.scheduled_for.asc())
                .limit(self._batch_size)
            )
            pending = result.scalars().all()

            if not pending:
                return summary

            logger.info("sms_dispatch_batch_start", count=len(pending))

            for sched in pending:
                if not _within_send_window():
                    sched.status = "pending"
                    summary["skipped"] += 1
                    logger.info(
                        "sms_outside_send_window",
                        sched_id=str(sched.id),
                    )
                    continue

                try:
                    twilio_result = await self._twilio.send_sms(
                        to=sched.phone_to,
                        body=sched.body,
                        status_callback=settings.twilio_status_callback_url or None,
                    )

                    sched.status = "sent"
                    sched.sent_at = datetime.now(timezone.utc)

                    from backend.models.message import Message
                    from uuid import uuid4

                    safe_extra = {}
                    for k, v in (twilio_result or {}).items():
                        if isinstance(v, datetime):
                            safe_extra[k] = v.isoformat()
                        elif hasattr(v, "isoformat"):
                            safe_extra[k] = v.isoformat()
                        else:
                            try:
                                import json
                                json.dumps(v)
                                safe_extra[k] = v
                            except (TypeError, ValueError):
                                safe_extra[k] = str(v)

                    msg = Message(
                        external_id=twilio_result.get("sid", ""),
                        direction="outbound",
                        phone_from=settings.twilio_phone_number,
                        phone_to=sched.phone_to,
                        body=sched.body,
                        status="sent",
                        sent_at=sched.sent_at,
                        guest_id=sched.guest_id,
                        reservation_id=sched.reservation_id,
                        is_auto_response=True,
                        provider="twilio",
                        cost_amount=(
                            float(twilio_result["price"])
                            if twilio_result.get("price")
                            else None
                        ),
                        num_segments=int(twilio_result.get("num_segments") or 1),
                        trace_id=uuid4(),
                        extra_data=safe_extra,
                    )
                    db.add(msg)
                    sched.message_id = msg.id

                    summary["sent"] += 1
                    logger.info(
                        "sms_dispatched",
                        sched_id=str(sched.id),
                        sid=twilio_result.get("sid"),
                        to=sched.phone_to,
                    )

                except Exception as exc:
                    sched.status = "failed"
                    sched.error_message = str(exc)[:500]
                    summary["failed"] += 1
                    logger.error(
                        "sms_dispatch_failed",
                        sched_id=str(sched.id),
                        to=sched.phone_to,
                        error=str(exc)[:300],
                    )

            await db.commit()

        return summary

    async def run_loop(self):
        """Infinite polling loop. Safe for asyncio.create_task()."""
        self._running = True
        logger.info(
            "sms_dispatch_worker_starting",
            poll_interval=self._poll_interval,
            batch_size=self._batch_size,
            send_window=f"{settings.message_send_start_hour}:00-{settings.message_send_end_hour}:00",
        )

        await asyncio.sleep(3)

        while self._running:
            self._cycle_count += 1
            t0 = time.perf_counter()
            try:
                summary = await self.dispatch_batch()
                elapsed = round((time.perf_counter() - t0) * 1000)
                if summary["sent"] or summary["failed"]:
                    logger.info(
                        "sms_dispatch_cycle_complete",
                        cycle=self._cycle_count,
                        elapsed_ms=elapsed,
                        **summary,
                    )
            except Exception as exc:
                logger.error(
                    "sms_dispatch_cycle_error",
                    cycle=self._cycle_count,
                    error=str(exc)[:500],
                )

            await asyncio.sleep(self._poll_interval)

    def stop(self):
        """Signal the worker to exit after the current cycle."""
        self._running = False
        logger.info("sms_dispatch_worker_stop_requested")


def _within_send_window() -> bool:
    """Respect the configured quiet-hours window."""
    hour = datetime.now(timezone.utc).hour
    return settings.message_send_start_hour <= hour < settings.message_send_end_hour


async def run_standalone():
    """Entry point for standalone daemon mode."""
    worker = SmsDispatchWorker()
    try:
        await worker.run_loop()
    except KeyboardInterrupt:
        worker.stop()
        logger.info("sms_dispatch_worker_interrupted")


if __name__ == "__main__":
    asyncio.run(run_standalone())
