"""
VRS Infrastructure — ARQ-backed event publishing for decoupled rule dispatch.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal
from backend.services.async_jobs import count_jobs_by_status, enqueue_async_job

if TYPE_CHECKING:
    from backend.vrs.domain.automations import StreamlineEventPayload

logger = structlog.get_logger(service="vrs.event_bus")

EVENT_QUEUE_KEY = "process_streamline_event_job"
DLQ_KEY = "process_streamline_event_job:failed"

redis_client = None

# ---------------------------------------------------------------------------
# High-level helpers (kept for backward compat & convenience)
# ---------------------------------------------------------------------------


async def publish_vrs_event(
    event: "StreamlineEventPayload",
    db: Optional[AsyncSession] = None,
) -> bool:
    """Persist and enqueue one VRS event for ARQ worker execution."""
    owns_session = db is None
    session = db
    if session is None:
        session = AsyncSessionLocal()
    try:
        job = await enqueue_async_job(
            session,
            worker_name="process_streamline_event_job",
            job_name="process_streamline_event",
            payload=event.model_dump(mode="json"),
            requested_by="vrs_event_bus",
            tenant_id=None,
            request_id=None,
        )
        logger.info(
            "event_publish_enqueued",
            job_id=str(job.id),
            entity=event.entity_type,
            event_type=event.event_type,
        )
        return True
    except Exception as exc:
        logger.warning("event_publish_failed", error=str(exc), entity=event.entity_type)
        return False
    finally:
        if owns_session and session is not None:
            await session.aclose()


async def consume_one(timeout: int = 5) -> Optional["StreamlineEventPayload"]:
    """ARQ replaces direct queue consumption; retained for backward compatibility."""
    _ = timeout
    return None


async def send_to_dlq(raw_payload: str, error: str) -> None:
    """The persistent job table now acts as the dead-letter ledger."""
    logger.error("vrs_event_dlq_recorded", payload=raw_payload[:500], error=error[:500])


async def queue_depth() -> int:
    """Return queued VRS event jobs waiting in the async job table."""
    try:
        async with AsyncSessionLocal() as db:
            return await count_jobs_by_status(
                db,
                status="queued",
                job_name="process_streamline_event",
            )
    except Exception:
        return -1


async def dlq_depth() -> int:
    """Return failed VRS event jobs recorded in the async job table."""
    try:
        async with AsyncSessionLocal() as db:
            return await count_jobs_by_status(
                db,
                status="failed",
                job_name="process_streamline_event",
            )
    except Exception:
        return -1


async def close() -> None:
    """No-op compatibility hook; pool lifecycle is managed by FastAPI and ARQ."""
    return None
