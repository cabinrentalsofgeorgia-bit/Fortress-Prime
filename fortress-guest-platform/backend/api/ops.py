"""Staff-protected operational tooling (queue repair, archives, etc.)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.staff import StaffRole, StaffUser
from backend.services.async_job_archive import archive_async_job_history

router = APIRouter(prefix="/system/ops", tags=["Operations"])

CONTROL_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])


class AsyncJobArchivePreviewItemOut(BaseModel):
    id: str
    job_name: str
    status: str
    finished_at: str | None
    error_text: str | None


class AsyncJobArchivePruneRequest(BaseModel):
    older_than_minutes: int = Field(default=60, ge=1, le=525600)
    limit: int = Field(default=500, ge=1, le=10_000)
    statuses: list[str] | None = Field(
        default=None,
        description="Ledger statuses to include. Defaults to failed and cancelled.",
    )
    apply: bool = Field(default=False, description="If true, write JSONL and delete rows.")
    output_path: str | None = Field(
        default=None,
        description="Optional absolute path for the archive file; default uses artifacts dir.",
    )


class AsyncJobArchivePruneResponse(BaseModel):
    matched_rows: int
    statuses: list[str]
    older_than_minutes: int
    cutoff_utc: str
    apply: bool
    preview: list[AsyncJobArchivePreviewItemOut]
    preview_truncated: int
    archived_rows: int
    archive_path: str | None


@router.post(
    "/async-jobs/archive-prune",
    response_model=AsyncJobArchivePruneResponse,
    summary="Archive and prune historical async_job_runs (dry-run by default)",
)
async def post_async_job_archive_prune(
    body: AsyncJobArchivePruneRequest,
    db=Depends(get_db),
    _: StaffUser = Depends(CONTROL_ACCESS),
) -> AsyncJobArchivePruneResponse:
    out_path = Path(body.output_path).expanduser() if body.output_path else None
    result = await archive_async_job_history(
        db,
        older_than_minutes=body.older_than_minutes,
        statuses=body.statuses,
        limit=body.limit,
        apply=body.apply,
        output_path=out_path,
    )
    return AsyncJobArchivePruneResponse(
        matched_rows=result.matched_rows,
        statuses=list(result.statuses),
        older_than_minutes=result.older_than_minutes,
        cutoff_utc=result.cutoff_utc,
        apply=result.apply,
        preview=[
            AsyncJobArchivePreviewItemOut(
                id=p.id,
                job_name=p.job_name,
                status=p.status,
                finished_at=p.finished_at,
                error_text=p.error_text,
            )
            for p in result.preview
        ],
        preview_truncated=result.preview_truncated,
        archived_rows=result.archived_rows,
        archive_path=result.archive_path,
    )
