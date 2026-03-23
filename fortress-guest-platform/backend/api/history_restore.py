"""
On-demand restoration endpoints for historical Drupal archive content.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.services.archive_restoration import (
    ArchiveBlueprintUnavailable,
    ArchiveRecordNotFound,
    ArchiveRestorationService,
)

router = APIRouter()
archive_restoration_service = ArchiveRestorationService()


class ArchiveRestoreResponse(BaseModel):
    slug: str
    status: str
    lookup_backend: str
    persisted: bool
    cache_path: str
    archive_path: str
    record: dict[str, Any]


@router.get("/api/v1/history/restore/{legacy_path:path}", response_model=ArchiveRestoreResponse)
async def restore_historical_archive(legacy_path: str, force_sign: bool = False):
    try:
        result = await archive_restoration_service.restore_archive(legacy_path, force_sign=force_sign)
    except ArchiveRecordNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ArchiveBlueprintUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return ArchiveRestoreResponse(
        slug=result.slug,
        status=result.status,
        lookup_backend=result.lookup_backend,
        persisted=result.persisted,
        cache_path=result.cache_path,
        archive_path=result.archive_path,
        record=result.record,
    )
