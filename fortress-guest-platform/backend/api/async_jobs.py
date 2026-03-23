"""
ARQ-backed asynchronous job submission and status endpoints.
"""
from __future__ import annotations

from typing import Any, Optional

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.services.async_jobs import (
    enqueue_async_job,
    extract_request_actor,
    get_async_job,
    list_async_jobs,
    serialize_async_job,
)

router = APIRouter()


class AsyncJobResponse(BaseModel):
    id: str
    job_name: str
    queue_name: str
    status: str
    requested_by: Optional[str] = None
    tenant_id: Optional[str] = None
    request_id: Optional[str] = None
    arq_job_id: Optional[str] = None
    attempts: int
    payload: dict[str, Any]
    result: dict[str, Any]
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None


class AsyncJobListResponse(BaseModel):
    jobs: list[AsyncJobResponse]
    count: int


class KnowledgeReembedRequest(BaseModel):
    reason: str = Field(default="command_center")


class VectorizeRequest(BaseModel):
    trigger: str = Field(default="command_center")


class HistoryIndexRequest(BaseModel):
    history_path: str = Field(default="/mnt/history")


class ArchiveSeoBatchRequest(BaseModel):
    archive_dir: Optional[str] = None
    api_base_url: Optional[str] = None
    chat_completions_url: Optional[str] = None
    model: Optional[str] = None
    campaign: str = Field(default="archive_async_engine")
    rubric_version: str = Field(default="nemotron_archive_v1")
    proposed_by: str = Field(default="dgx-nemotron")
    run_id: Optional[str] = None
    concurrency: int = Field(default=4, ge=1, le=16)
    limit: Optional[int] = Field(default=500, ge=1, le=5000)
    only_slug: Optional[str] = None
    post_api: bool = False
    dry_run: bool = False
    write_db: bool = True
    disable_thinking: bool = True
    force_json_response: bool = True
    db_resume: bool = True


class SeoRedirectBatchRequest(BaseModel):
    input_path: str = Field(
        default="/home/admin/Fortress-Prime/fortress-guest-platform/backend/scripts/seo_migration_candidates_batch2_1617.json"
    )
    source_key: str = Field(default="redirects")
    offset: int = Field(default=0, ge=0)
    limit: Optional[int] = Field(default=None, ge=1, le=10000)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    write_db: bool = True


class SeoFallbackSwarmRequest(BaseModel):
    preview_path: Optional[str] = None
    campaign: str = Field(default="seo_fallback_swarm")
    rubric_version: str = Field(default="seo_redirect_remap_v1")
    proposal_run_id: Optional[str] = None
    model: Optional[str] = None
    offset: int = Field(default=0, ge=0)
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class SeoRemapGradingRequest(BaseModel):
    campaign: str = Field(default="seo_fallback_swarm_live")
    model: Optional[str] = None
    threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class SeoDeepEntitySwarmRequest(BaseModel):
    confidence_ceiling: float = Field(default=0.50, ge=0.0, le=1.0)
    campaign: str = Field(default="deep_entity_swarm")
    source_campaign: Optional[str] = Field(default=None)
    rubric_version: str = Field(default="seo_deep_entity_v1")
    proposal_run_id: Optional[str] = None
    model: Optional[str] = None
    offset: int = Field(default=0, ge=0)
    limit: Optional[int] = Field(default=None, ge=1, le=500)


def _actor_from_request(request: Request) -> str:
    return extract_request_actor(
        request.headers.get("x-user-id"),
        request.headers.get("x-user-email"),
    )


def _job_response(job) -> AsyncJobResponse:
    return AsyncJobResponse(**serialize_async_job(job))


@router.get("/api/async/jobs/{job_id}", response_model=AsyncJobResponse)
async def get_async_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await get_async_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _job_response(job)


@router.get("/api/async/jobs", response_model=AsyncJobListResponse)
async def list_async_job_statuses(
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    job_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    jobs = await list_async_jobs(db, limit=limit, status=status_filter, job_name=job_name)
    return AsyncJobListResponse(jobs=[_job_response(job) for job in jobs], count=len(jobs))


@router.post(
    "/api/async/jobs/knowledge-reembed",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_knowledge_reembed_job(
    body: KnowledgeReembedRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="sync_knowledge_base_job",
        job_name="sync_knowledge_base",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/vectorize",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_vectorize_job(
    body: VectorizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="vectorize_new_records_job",
        job_name="vectorize_new_records",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/history-index",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_history_index_job(
    body: HistoryIndexRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="rebuild_history_index_job",
        job_name="rebuild_history_index",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/seo-archive-batch",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_archive_seo_batch_job(
    body: ArchiveSeoBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_archive_seo_batch_job",
        job_name="run_archive_seo_batch",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/seo-redirect-batch",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_seo_redirect_batch_job(
    body: SeoRedirectBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_seo_redirect_batch_job",
        job_name="run_seo_redirect_batch",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/seo-fallback-swarm",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_seo_fallback_swarm_job(
    body: SeoFallbackSwarmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_seo_fallback_swarm_job",
        job_name="run_seo_fallback_swarm",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/seo-remap-grading",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_seo_remap_grading_job(
    body: SeoRemapGradingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_seo_remap_grading_job",
        job_name="run_seo_remap_grading",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)


@router.post(
    "/api/async/jobs/seo-deep-entity-swarm",
    response_model=AsyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_deep_entity_swarm_job(
    body: SeoDeepEntitySwarmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    job = await enqueue_async_job(
        db,
        worker_name="run_deep_entity_swarm_job",
        job_name="run_deep_entity_swarm",
        payload=body.model_dump(),
        requested_by=_actor_from_request(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    return _job_response(job)
