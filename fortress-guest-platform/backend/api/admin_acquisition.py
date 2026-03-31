"""
Admin acquisition API for CROG property-intel ingestion.
"""
from __future__ import annotations

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.async_jobs import AsyncJobResponse
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.core.security import require_admin
from backend.models.staff import StaffUser
from backend.services.airdna_client import AirDNASyncJobPayload
from backend.services.acquisition_ingestion import AcquisitionIngestionRequest
from backend.services.async_jobs import enqueue_async_job, serialize_async_job
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger(service="admin_acquisition_api")
router = APIRouter()


@router.post(
    "/acquisition/ingest",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_acquisition_ingestion(
    payload: AcquisitionIngestionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
    user: StaffUser = Depends(require_admin),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_acquisition_ingestion_job",
        job_name="acquisition_ingestion_cycle",
        payload=payload.model_dump(mode="json"),
        requested_by=user.email,
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="admin.acquisition.ingest",
        resource_type="crog_acquisition",
        resource_id=str(job.id),
        purpose="queue parcel and STR registry intelligence ingestion",
        outcome="accepted",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "dry_run": payload.dry_run,
            "county_name": payload.county_name,
            "has_qpublic_url": bool(payload.qpublic_url),
            "has_str_permits_url": bool(payload.str_permits_url),
            "parcel_seed_records": len(payload.parcel_seed_records),
            "str_seed_records": len(payload.str_seed_records),
        },
        db=db,
    )
    logger.info(
        "admin_acquisition_ingestion_enqueued",
        actor_id=str(user.id),
        job_id=str(job.id),
        county_name=payload.county_name,
        dry_run=payload.dry_run,
    )
    return AsyncJobResponse(**serialize_async_job(job))


@router.post(
    "/acquisition/airdna/sync",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_airdna_sync(
    payload: AirDNASyncJobPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
    user: StaffUser = Depends(require_admin),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_airdna_sync_job",
        job_name="airdna_str_signal_sync",
        payload=payload.model_dump(mode="json"),
        requested_by=user.email,
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="admin.acquisition.airdna_sync",
        resource_type="crog_acquisition",
        resource_id=str(job.id),
        purpose="queue AirDNA STR signal synchronization",
        outcome="accepted",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "market": payload.market,
            "dry_run": payload.dry_run,
        },
        db=db,
    )
    logger.info(
        "admin_acquisition_airdna_sync_enqueued",
        actor_id=str(user.id),
        job_id=str(job.id),
        market=payload.market,
        dry_run=payload.dry_run,
    )
    return AsyncJobResponse(**serialize_async_job(job))
