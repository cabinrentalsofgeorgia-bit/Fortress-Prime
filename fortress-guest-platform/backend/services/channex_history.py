"""
Read recent Channex remediation history from the OpenShell audit ledger.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.openshell_audit import OpenShellAuditLog


class ChannexHistoryItem(BaseModel):
    id: str
    action: str
    outcome: str
    actor_email: str | None
    created_at: str
    request_id: str | None
    property_count: int | None = None
    remediated_count: int | None = None
    failed_count: int | None = None
    ari_window_days: int | None = None
    results: list[dict[str, Any]]


class ChannexHistoryResponse(BaseModel):
    count: int
    recent_success_count: int
    recent_partial_failure_count: int
    recent_remediated_property_count: int
    recent_failed_property_count: int
    last_run_at: str | None = None
    last_success_at: str | None = None
    items: list[ChannexHistoryItem]


async def get_channex_remediation_history(
    db: AsyncSession,
    *,
    limit: int = 20,
) -> ChannexHistoryResponse:
    stmt = (
        select(OpenShellAuditLog)
        .where(OpenShellAuditLog.action == "admin.channex.remediate")
        .order_by(desc(OpenShellAuditLog.created_at))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        ChannexHistoryItem(
            id=str(row.id),
            action=row.action,
            outcome=row.outcome,
            actor_email=row.actor_email,
            created_at=_iso(row.created_at),
            request_id=row.request_id,
            property_count=_int(meta(row).get("property_count")),
            remediated_count=_int(meta(row).get("remediated_count")),
            failed_count=_int(meta(row).get("failed_count")),
            ari_window_days=_int(meta(row).get("ari_window_days")),
            results=_list(meta(row).get("results")),
        )
        for row in rows
    ]
    last_run_at = items[0].created_at if items else None
    last_success_at = next((item.created_at for item in items if item.outcome == "success"), None)
    return ChannexHistoryResponse(
        count=len(items),
        recent_success_count=sum(1 for item in items if item.outcome == "success"),
        recent_partial_failure_count=sum(1 for item in items if item.outcome != "success"),
        recent_remediated_property_count=sum(item.remediated_count or 0 for item in items),
        recent_failed_property_count=sum(item.failed_count or 0 for item in items),
        last_run_at=last_run_at,
        last_success_at=last_success_at,
        items=items,
    )


def meta(row: OpenShellAuditLog) -> dict[str, Any]:
    return row.metadata_json if isinstance(row.metadata_json, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _iso(value: datetime) -> str:
    return value.isoformat()
