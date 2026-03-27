"""
Archive and prune historical async_job_runs rows.

Safe for use inside FastAPI: accepts a request-scoped AsyncSession and does not
dispose the global database engine.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.async_job import AsyncJobRun


@dataclass(slots=True)
class ArchivedAsyncJobRow:
    id: str
    job_name: str
    queue_name: str
    status: str
    requested_by: str | None
    tenant_id: str | None
    request_id: str | None
    arq_job_id: str | None
    attempts: int
    payload_json: dict[str, Any]
    result_json: dict[str, Any]
    error_text: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    updated_at: str | None


@dataclass(slots=True)
class AsyncJobArchivePreviewItem:
    id: str
    job_name: str
    status: str
    finished_at: str | None
    error_text: str | None


@dataclass(slots=True)
class AsyncJobArchiveResult:
    matched_rows: int
    statuses: tuple[str, ...]
    older_than_minutes: int
    cutoff_utc: str
    apply: bool
    preview: list[AsyncJobArchivePreviewItem]
    preview_truncated: int
    archived_rows: int
    archive_path: str | None


def default_archive_output_path(*, app_root: Path | None = None) -> Path:
    """Default JSONL path under fortress-guest-platform/backend/artifacts/..."""
    if app_root is None:
        app_root = Path(__file__).resolve().parents[2]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return app_root / "backend" / "artifacts" / "async-job-archives" / f"async-job-archive-{timestamp}.jsonl"


def _serialize_rows(rows: Iterable[AsyncJobRun]) -> list[ArchivedAsyncJobRow]:
    serialized: list[ArchivedAsyncJobRow] = []
    for row in rows:
        serialized.append(
            ArchivedAsyncJobRow(
                id=str(row.id),
                job_name=row.job_name,
                queue_name=row.queue_name,
                status=row.status,
                requested_by=row.requested_by,
                tenant_id=row.tenant_id,
                request_id=row.request_id,
                arq_job_id=row.arq_job_id,
                attempts=int(row.attempts or 0),
                payload_json=row.payload_json or {},
                result_json=row.result_json or {},
                error_text=row.error_text,
                created_at=row.created_at.isoformat() if row.created_at else None,
                started_at=row.started_at.isoformat() if row.started_at else None,
                finished_at=row.finished_at.isoformat() if row.finished_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
        )
    return serialized


async def archive_async_job_history(
    db: AsyncSession,
    *,
    older_than_minutes: int = 60,
    statuses: list[str] | None = None,
    limit: int = 500,
    apply: bool = False,
    output_path: Path | None = None,
    app_root: Path | None = None,
) -> AsyncJobArchiveResult:
    """
    Select failed/cancelled async_job_runs older than cutoff.

    When apply is False, returns preview only (no file write, no deletes).
    When apply is True, writes JSONL and deletes selected rows in the same transaction.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, int(older_than_minutes)))
    status_tuple = tuple(dict.fromkeys(statuses or ["failed", "cancelled"]))
    resolved_output = output_path if output_path is not None else default_archive_output_path(app_root=app_root)

    cutoff_expr = func.coalesce(AsyncJobRun.finished_at, AsyncJobRun.created_at)
    stmt = (
        select(AsyncJobRun)
        .where(AsyncJobRun.status.in_(status_tuple))
        .where(cutoff_expr <= cutoff)
        .order_by(cutoff_expr.asc(), AsyncJobRun.created_at.asc())
        .limit(max(1, int(limit)))
    )
    rows = list((await db.execute(stmt)).scalars().all())
    archive_rows = _serialize_rows(rows)

    preview: list[AsyncJobArchivePreviewItem] = []
    preview_limit = 10
    for row in archive_rows[:preview_limit]:
        preview.append(
            AsyncJobArchivePreviewItem(
                id=row.id,
                job_name=row.job_name,
                status=row.status,
                finished_at=row.finished_at,
                error_text=row.error_text,
            )
        )
    preview_truncated = max(0, len(archive_rows) - preview_limit)

    archived_count = 0
    archive_path_str: str | None = None

    if apply and archive_rows:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        with resolved_output.open("w", encoding="utf-8") as handle:
            for row in archive_rows:
                handle.write(json.dumps(asdict(row), sort_keys=True) + "\n")

        row_ids = [r.id for r in archive_rows]
        await db.execute(delete(AsyncJobRun).where(AsyncJobRun.id.in_(row_ids)))
        await db.commit()
        archived_count = len(archive_rows)
        archive_path_str = str(resolved_output)
    else:
        # Dry-run or apply with nothing matched: end read-only transaction cleanly.
        await db.rollback()

    return AsyncJobArchiveResult(
        matched_rows=len(archive_rows),
        statuses=status_tuple,
        older_than_minutes=int(older_than_minutes),
        cutoff_utc=cutoff.isoformat(),
        apply=apply,
        preview=preview,
        preview_truncated=preview_truncated,
        archived_rows=archived_count,
        archive_path=archive_path_str,
    )
