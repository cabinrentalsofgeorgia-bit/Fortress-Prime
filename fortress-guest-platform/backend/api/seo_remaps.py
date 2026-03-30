"""
Redirect remap queue API for swarm proposals and God Head sealing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.core.security_swarm import verify_swarm_token
from backend.models import SeoRedirect, SeoRedirectRemapQueue
from backend.models.staff import StaffUser
from backend.services.openshell_audit import record_audit_event

router = APIRouter()
VALID_STATUSES = {"proposed", "promoted", "rejected", "applied", "superseded"}


class SeoRemapQueueItem(BaseModel):
    id: str
    source_path: str
    current_destination_path: Optional[str] = None
    proposed_destination_path: str
    applied_destination_path: Optional[str] = None
    grounding_mode: str
    status: str
    campaign: str
    rubric_version: str
    proposal_run_id: str
    proposed_by: str
    extracted_entities: list[str]
    source_snapshot: dict[str, Any]
    route_candidates: list[str]
    rationale: str
    grade_score: Optional[float] = None
    grade_payload: dict[str, Any]
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SeoRemapQueueResponse(BaseModel):
    items: list[SeoRemapQueueItem]
    total: int
    offset: int
    limit: int


class SeoRemapReviewRequest(BaseModel):
    note: Optional[str] = None


class SeoRemapGradeResultRequest(BaseModel):
    review_id: UUID
    score: float = Field(..., ge=0.0, le=1.0)
    rubric_version: str = Field(default="seo_redirect_remap_v1", max_length=50)
    verdict: str = Field(default="candidate")
    note: Optional[str] = None
    breakdown: dict[str, float] = Field(default_factory=dict)
    grader: str = Field(default="god_head", max_length=100)


def _to_payload(row: SeoRedirectRemapQueue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_path": row.source_path,
        "current_destination_path": row.current_destination_path,
        "proposed_destination_path": row.proposed_destination_path,
        "applied_destination_path": row.applied_destination_path,
        "grounding_mode": row.grounding_mode,
        "status": row.status,
        "campaign": row.campaign,
        "rubric_version": row.rubric_version,
        "proposal_run_id": row.proposal_run_id,
        "proposed_by": row.proposed_by,
        "extracted_entities": row.extracted_entities or [],
        "source_snapshot": row.source_snapshot or {},
        "route_candidates": row.route_candidates or [],
        "rationale": row.rationale,
        "grade_score": row.grade_score,
        "grade_payload": row.grade_payload or {},
        "reviewed_by": row.reviewed_by,
        "review_note": row.review_note,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

@router.get("/queue", response_model=SeoRemapQueueResponse)
async def list_remap_queue(
    status_filter: str = Query("promoted", alias="status"),
    campaign: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    status_value = (status_filter or "promoted").strip().lower()
    if status_value not in VALID_STATUSES and status_value != "all":
        raise HTTPException(status_code=400, detail="invalid status filter")

    query = select(SeoRedirectRemapQueue).order_by(SeoRedirectRemapQueue.created_at.desc())
    count_query = select(func.count(SeoRedirectRemapQueue.id))
    if status_value != "all":
        query = query.where(SeoRedirectRemapQueue.status == status_value)
        count_query = count_query.where(SeoRedirectRemapQueue.status == status_value)
    if campaign:
        query = query.where(SeoRedirectRemapQueue.campaign == campaign)
        count_query = count_query.where(SeoRedirectRemapQueue.campaign == campaign)

    rows = (await db.execute(query.limit(limit).offset(offset))).scalars().all()
    total = int((await db.execute(count_query)).scalar() or 0)
    return SeoRemapQueueResponse(
        items=[SeoRemapQueueItem(**_to_payload(row)) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{remap_id:uuid}")
async def get_remap_detail(
    remap_id: UUID,
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoRedirectRemapQueue, remap_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO remap not found")
    return {"item": _to_payload(row)}


@router.post("/grade-results")
async def ingest_grade_result(
    body: SeoRemapGradeResultRequest,
    _swarm_token: str = Depends(verify_swarm_token),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoRedirectRemapQueue, body.review_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO remap not found")

    threshold = float(settings.seo_redirect_grade_threshold)
    row.grade_score = float(body.score)
    row.grade_payload = {
        "grader": body.grader,
        "verdict": body.verdict,
        "note": body.note,
        "breakdown": body.breakdown,
        "threshold": threshold,
        "rubric_version": body.rubric_version,
    }
    row.rubric_version = body.rubric_version
    row.review_note = (body.note or "").strip() or row.review_note
    row.reviewed_by = body.grader.strip() or "swarm"
    row.status = "promoted" if body.score >= threshold else "rejected"
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload(row)}


@router.post("/{remap_id:uuid}/approve")
async def approve_remap(
    remap_id: UUID,
    body: SeoRemapReviewRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoRedirectRemapQueue, remap_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO remap not found")
    if row.status not in {"promoted", "proposed"}:
        raise HTTPException(status_code=409, detail=f"Cannot approve remap in '{row.status}' state")

    redirect = (
        await db.execute(select(SeoRedirect).where(SeoRedirect.source_path == row.source_path))
    ).scalar_one_or_none()
    if redirect is None:
        redirect = SeoRedirect(
            source_path=row.source_path,
            destination_path=row.proposed_destination_path,
            is_permanent=True,
            reason="REMAP[GodHead-Sealed]",
            created_by=user.email,
            updated_by=user.email,
            is_active=True,
        )
        db.add(redirect)
    else:
        redirect.destination_path = row.proposed_destination_path
        redirect.is_permanent = True
        redirect.is_active = True
        redirect.reason = f"REMAP[GodHead-Sealed][GRADE={row.grade_score or 0:.3f}]"
        redirect.updated_by = user.email

    siblings = (
        await db.execute(
            select(SeoRedirectRemapQueue).where(
                SeoRedirectRemapQueue.source_path == row.source_path,
                SeoRedirectRemapQueue.id != row.id,
                SeoRedirectRemapQueue.status.in_(["promoted", "proposed", "rejected"]),
            )
        )
    ).scalars().all()
    for sibling in siblings:
        sibling.status = "superseded"
        sibling.updated_at = datetime.utcnow()

    row.status = "applied"
    row.applied_destination_path = row.proposed_destination_path
    row.reviewed_by = user.email
    row.review_note = (body.note or "").strip() or row.review_note
    row.approved_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)

    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="seo.redirect_remap.approved",
        resource_type="seo_redirect_remap",
        resource_id=str(row.id),
        purpose="seo_redirect_hitl",
        tool_name="seo_remaps.approve",
        redaction_status="not_applicable",
        model_route="god_head_seal",
        outcome="success",
        metadata_json={
            "source_path": row.source_path,
            "proposed_destination_path": row.proposed_destination_path,
            "grade_score": row.grade_score,
        },
        db=db,
    )
    return {"ok": True, "item": _to_payload(row)}


@router.post("/{remap_id:uuid}/reject")
async def reject_remap(
    remap_id: UUID,
    body: SeoRemapReviewRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="review_note_required_for_reject")

    row = await db.get(SeoRedirectRemapQueue, remap_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO remap not found")

    row.status = "rejected"
    row.reviewed_by = user.email
    row.review_note = note
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload(row)}
