"""
Admin FOIA ingestion routes for deterministic county STR drops.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import uuid

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.async_jobs import AsyncJobResponse
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.core.security import require_admin
from backend.models.staff import StaffUser
from backend.services.acquisition_foia import FoiaIngestJobPayload
from backend.services.async_jobs import enqueue_async_job, serialize_async_job
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger(service="admin_acquisition_foia_api")
router = APIRouter()


@router.post(
    "/api/v1/ingest/foia/fannin-str",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_fannin_foia_ingest(
    request: Request,
    upload: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    county_name: str = Form(default="Fannin"),
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
    user: StaffUser = Depends(require_admin),
):
    file_bytes = await upload.read()
    suffix = Path(upload.filename or "foia.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(file_bytes)
        spool_path = handle.name

    payload = FoiaIngestJobPayload(
        spool_path=spool_path,
        filename=upload.filename or Path(spool_path).name,
        dry_run=dry_run,
        county_name=county_name,
    )
    job = await enqueue_async_job(
        db,
        worker_name="run_fannin_foia_ingest_job",
        job_name="foia_fannin_str_ingest",
        payload=payload.model_dump(mode="json"),
        requested_by=user.email,
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id") or f"foia-{uuid.uuid4()}",
        redis=arq_redis,
    )
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="admin.acquisition.foia_ingest",
        resource_type="crog_acquisition_foia",
        resource_id=str(job.id),
        purpose="queue deterministic Fannin County STR FOIA ingest",
        outcome="accepted",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "filename": payload.filename,
            "county_name": county_name,
            "dry_run": dry_run,
            "spool_path": spool_path,
        },
        db=db,
    )
    logger.info(
        "admin_acquisition_foia_enqueued",
        actor_id=str(user.id),
        filename=payload.filename,
        county_name=county_name,
        job_id=str(job.id),
    )
    return AsyncJobResponse(**serialize_async_job(job))
