"""
SEO migration audit queue endpoints for HITL review.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.seo_redirect import SeoRedirect
from backend.models.staff import StaffUser
from backend.services.openshell_audit import record_audit_event

router = APIRouter()

_CONF_RE = re.compile(r"\[CONF=(?P<score>\d+(?:\.\d+)?)\]")


class SeoAuditRow(BaseModel):
    id: str
    source_path: str
    destination_path: str
    confidence: float
    status: str
    reason: Optional[str] = None
    is_permanent: bool
    is_active: bool
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class SeoAuditQueueResponse(BaseModel):
    queue: list[SeoAuditRow]
    count: int


class SeoApproveResponse(BaseModel):
    status: str
    audit_id: Optional[str]
    redirect_id: str


def _extract_actor(request: Request) -> tuple[Optional[str], Optional[str]]:
    return request.headers.get("x-user-id"), request.headers.get("x-user-email")


def _status_from_reason(row: SeoRedirect) -> str:
    reason = (row.reason or "").upper()
    if not row.is_active:
        return "inactive"
    if "[REJECTED]" in reason:
        return "rejected"
    if "[APPROVED]" in reason:
        return "approved"
    return "pending"


def _confidence_from_reason(reason: Optional[str]) -> float:
    if not reason:
        return 0.0
    match = _CONF_RE.search(reason)
    if not match:
        return 0.0
    try:
        return float(match.group("score"))
    except ValueError:
        return 0.0


@router.get("/api/v1/seo/audit-queue", response_model=SeoAuditQueueResponse)
async def get_seo_audit_queue(
    status_filter: str = "pending",
    limit: int = 1000,
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    status_norm = (status_filter or "pending").lower()
    if status_norm not in {"pending", "approved", "rejected", "inactive", "all"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid status filter")

    rows = (await db.execute(select(SeoRedirect))).scalars().all()
    queue: list[SeoAuditRow] = []
    for row in rows:
        row_status = _status_from_reason(row)
        if status_norm != "all" and row_status != status_norm:
            continue
        queue.append(
            SeoAuditRow(
                id=str(row.id),
                source_path=row.source_path,
                destination_path=row.destination_path,
                confidence=_confidence_from_reason(row.reason),
                status=row_status,
                reason=row.reason,
                is_permanent=row.is_permanent,
                is_active=row.is_active,
                created_by=row.created_by,
                updated_by=row.updated_by,
            )
        )

    queue.sort(key=lambda item: item.confidence, reverse=True)
    if limit > 0:
        queue = queue[:limit]
    return SeoAuditQueueResponse(queue=queue, count=len(queue))


@router.post("/api/v1/seo/approve/{redirect_id}", response_model=SeoApproveResponse)
async def approve_redirect(
    redirect_id: str,
    request: Request,
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(SeoRedirect).where(SeoRedirect.id == redirect_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="redirect not found")

    actor_id, actor_email = _extract_actor(request)
    actor = actor_email or actor_id or "human_reviewer"
    reason = row.reason or ""
    reason_clean = reason.replace("[PENDING]", "").replace("[APPROVED]", "").strip()
    row.reason = f"[APPROVED] {reason_clean}".strip()
    row.updated_by = actor
    row.is_active = True
    await db.flush()

    audit_row = await record_audit_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="seo.redirect.approved",
        resource_type="seo_redirect",
        resource_id=str(row.id),
        purpose="human_review_hitl",
        tool_name="seo_audit.approve",
        redaction_status="not_applicable",
        model_route="review_queue",
        outcome="success",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "source_path": row.source_path,
            "destination_path": row.destination_path,
            "reason": row.reason,
        },
        db=db,
    )

    return SeoApproveResponse(status="committed", audit_id=getattr(audit_row, "entry_hash", None), redirect_id=str(row.id))
