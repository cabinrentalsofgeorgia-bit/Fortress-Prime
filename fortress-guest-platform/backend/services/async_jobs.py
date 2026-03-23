"""
Shared helpers for persistent ARQ-backed job orchestration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from arq.connections import ArqRedis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.queue import create_arq_pool
from backend.models.async_job import AsyncJobRun

logger = structlog.get_logger(service="async_jobs")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def extract_request_actor(requested_by: Optional[str], request_email: Optional[str]) -> str:
    actor = (request_email or requested_by or "").strip()
    return actor or "command_center"


async def enqueue_async_job(
    db: AsyncSession,
    *,
    worker_name: str,
    job_name: str,
    payload: dict[str, Any],
    requested_by: Optional[str] = None,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    redis: ArqRedis | None = None,
) -> AsyncJobRun:
    job = AsyncJobRun(
        job_name=job_name,
        queue_name=settings.arq_queue_name,
        status="queued",
        requested_by=requested_by,
        tenant_id=tenant_id,
        request_id=request_id,
        payload_json=payload,
        attempts=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    owns_pool = redis is None
    pool = redis or await create_arq_pool()
    try:
        enqueued = await pool.enqueue_job(
            worker_name,
            str(job.id),
            _job_id=str(job.id),
            _queue_name=settings.arq_queue_name,
        )
        if enqueued is None:
            raise RuntimeError(f"Failed to enqueue ARQ job for {job_name}")
        job.arq_job_id = str(job.id)
        await db.commit()
        await db.refresh(job)
        logger.info("async_job_enqueued", job_id=str(job.id), job_name=job_name, queue_name=settings.arq_queue_name)
        return job
    except Exception as exc:
        await mark_job_failed(db, job, str(exc), attempts=job.attempts)
        raise
    finally:
        if owns_pool:
            await pool.aclose()


async def get_async_job(db: AsyncSession, job_id: UUID | str) -> AsyncJobRun | None:
    return await db.get(AsyncJobRun, job_id)


async def list_async_jobs(
    db: AsyncSession,
    *,
    limit: int = 50,
    status: Optional[str] = None,
    job_name: Optional[str] = None,
) -> list[AsyncJobRun]:
    stmt = select(AsyncJobRun).order_by(desc(AsyncJobRun.created_at)).limit(limit)
    if status:
        stmt = stmt.where(AsyncJobRun.status == status)
    if job_name:
        stmt = stmt.where(AsyncJobRun.job_name == job_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_jobs_by_status(
    db: AsyncSession,
    *,
    status: str,
    job_name: Optional[str] = None,
) -> int:
    stmt = select(func.count()).select_from(AsyncJobRun).where(AsyncJobRun.status == status)
    if job_name:
        stmt = stmt.where(AsyncJobRun.job_name == job_name)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def mark_job_running(db: AsyncSession, job: AsyncJobRun, *, attempts: int) -> AsyncJobRun:
    job.status = "running"
    job.attempts = attempts
    if job.started_at is None:
        job.started_at = utcnow()
    job.error_text = None
    await db.commit()
    await db.refresh(job)
    return job


async def mark_job_succeeded(db: AsyncSession, job: AsyncJobRun, result: dict[str, Any]) -> AsyncJobRun:
    job.status = "succeeded"
    job.result_json = result
    job.finished_at = utcnow()
    job.error_text = None
    await db.commit()
    await db.refresh(job)
    return job


async def mark_job_failed(
    db: AsyncSession,
    job: AsyncJobRun,
    error_text: str,
    *,
    attempts: int,
) -> AsyncJobRun:
    job.status = "failed"
    job.attempts = attempts
    job.finished_at = utcnow()
    job.error_text = error_text[:4000]
    await db.commit()
    await db.refresh(job)
    return job


def serialize_async_job(job: AsyncJobRun) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "job_name": job.job_name,
        "queue_name": job.queue_name,
        "status": job.status,
        "requested_by": job.requested_by,
        "tenant_id": job.tenant_id,
        "request_id": job.request_id,
        "arq_job_id": job.arq_job_id,
        "attempts": job.attempts,
        "payload": job.payload_json or {},
        "result": job.result_json or {},
        "error": job.error_text,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
