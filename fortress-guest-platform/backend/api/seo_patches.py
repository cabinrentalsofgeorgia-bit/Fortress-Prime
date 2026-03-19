"""
SEO patch queue API for DGX swarm proposals and human approval.
"""
from __future__ import annotations

import hmac
import hashlib
import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import decode_token, get_current_user
from backend.models import Property, SeoPatchQueue
from backend.models.staff import StaffUser

router = APIRouter()


class SeoProposalPayload(BaseModel):
    title: str = Field(..., max_length=255)
    meta_description: str = Field(..., max_length=4000)
    h1: str = Field(..., max_length=255)
    intro: str = ""
    faq: list[dict[str, Any]] = Field(default_factory=list)
    json_ld: dict[str, Any] = Field(default_factory=dict)


class SeoGradingPayload(BaseModel):
    overall: float = Field(..., ge=0, le=100)
    breakdown: dict[str, float] = Field(default_factory=dict)


class SeoProposalRequest(BaseModel):
    property_id: Optional[UUID] = None
    property_slug: Optional[str] = None
    target_keyword: str = Field(..., max_length=255)
    campaign: str = Field(default="default", max_length=100)
    rubric_version: str = Field(default="v1", max_length=50)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    proposal: SeoProposalPayload
    grading: SeoGradingPayload
    proposed_by: str = Field(default="dgx-swarm", max_length=100)
    proposal_run_id: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def ensure_property_reference(self) -> "SeoProposalRequest":
        if not self.property_id and not (self.property_slug or "").strip():
            raise ValueError("Either property_id or property_slug is required")
        return self


class BulkProposalRequest(BaseModel):
    items: list[SeoProposalRequest]


class EditProposalRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    meta_description: Optional[str] = Field(default=None, max_length=4000)
    h1: Optional[str] = Field(default=None, max_length=255)
    intro: Optional[str] = None
    faq: Optional[list[dict[str, Any]]] = None
    json_ld: Optional[dict[str, Any]] = None


class ReviewDecisionRequest(BaseModel):
    note: Optional[str] = None


async def require_swarm_or_jwt(request: Request) -> dict[str, str]:
    """Allow proposal ingestion with either M2M swarm token or human JWT."""
    swarm_header = (request.headers.get("x-swarm-token") or "").strip()
    configured_swarm_key = (settings.swarm_api_key or "").strip()
    if configured_swarm_key and swarm_header and hmac.compare_digest(swarm_header, configured_swarm_key):
        return {"auth_mode": "swarm"}

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing valid Bearer token or X-Swarm-Token",
        )

    token = auth_header[7:]
    try:
        payload = decode_token(token)
        subject = payload.get("sub")
        if not subject:
            raise JWTError("Missing sub claim")
        return {"auth_mode": "jwt", "subject": str(subject)}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def _source_hash(*, property_id: UUID, campaign: str, rubric_version: str, source_snapshot: dict[str, Any]) -> str:
    basis = {
        "property_id": str(property_id),
        "campaign": campaign,
        "rubric_version": rubric_version,
        "source_snapshot": source_snapshot or {},
    }
    raw = json.dumps(basis, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _resolve_property_id(db: AsyncSession, body: SeoProposalRequest) -> UUID:
    if body.property_id:
        prop = await db.get(Property, body.property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        return prop.id

    result = await db.execute(
        select(Property).where(Property.slug == (body.property_slug or "").strip())
    )
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Property slug not found")
    return prop.id


def _to_payload_row(row: SeoPatchQueue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "property_id": str(row.property_id),
        "status": row.status,
        "target_keyword": row.target_keyword,
        "campaign": row.campaign,
        "rubric_version": row.rubric_version,
        "source_hash": row.source_hash,
        "proposed_title": row.proposed_title,
        "proposed_meta_description": row.proposed_meta_description,
        "proposed_h1": row.proposed_h1,
        "proposed_intro": row.proposed_intro,
        "proposed_faq": row.proposed_faq or [],
        "proposed_json_ld": row.proposed_json_ld or {},
        "fact_snapshot": row.fact_snapshot or {},
        "score_overall": row.score_overall,
        "score_breakdown": row.score_breakdown or {},
        "proposed_by": row.proposed_by,
        "proposal_run_id": row.proposal_run_id,
        "reviewed_by": row.reviewed_by,
        "review_note": row.review_note,
        "approved_payload": row.approved_payload or {},
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "deployed_at": row.deployed_at.isoformat() if row.deployed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _upsert_proposal(db: AsyncSession, body: SeoProposalRequest) -> SeoPatchQueue:
    property_id = await _resolve_property_id(db, body)
    source_hash = _source_hash(
        property_id=property_id,
        campaign=body.campaign,
        rubric_version=body.rubric_version,
        source_snapshot=body.source_snapshot,
    )
    result = await db.execute(
        select(SeoPatchQueue).where(
            SeoPatchQueue.property_id == property_id,
            SeoPatchQueue.campaign == body.campaign,
            SeoPatchQueue.source_hash == source_hash,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = SeoPatchQueue(
            property_id=property_id,
            campaign=body.campaign,
            source_hash=source_hash,
        )
        db.add(row)

    row.status = "proposed"
    row.target_keyword = body.target_keyword
    row.rubric_version = body.rubric_version
    row.proposed_title = body.proposal.title
    row.proposed_meta_description = body.proposal.meta_description
    row.proposed_h1 = body.proposal.h1
    row.proposed_intro = body.proposal.intro
    row.proposed_faq = body.proposal.faq
    row.proposed_json_ld = body.proposal.json_ld
    row.fact_snapshot = body.source_snapshot
    row.score_overall = body.grading.overall
    row.score_breakdown = body.grading.breakdown
    row.proposed_by = body.proposed_by
    row.proposal_run_id = body.proposal_run_id
    row.reviewed_by = None
    row.review_note = None
    row.approved_payload = {}
    row.approved_at = None
    row.deployed_at = None
    row.updated_at = datetime.utcnow()
    return row


@router.post("/proposals")
async def create_proposal(
    body: SeoProposalRequest,
    _auth: dict[str, str] = Depends(require_swarm_or_jwt),
    db: AsyncSession = Depends(get_db),
):
    row = await _upsert_proposal(db, body)
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload_row(row)}


@router.post("/bulk-proposals")
async def create_bulk_proposals(
    body: BulkProposalRequest,
    _auth: dict[str, str] = Depends(require_swarm_or_jwt),
    db: AsyncSession = Depends(get_db),
):
    items: list[dict[str, Any]] = []
    for item in body.items:
        row = await _upsert_proposal(db, item)
        items.append(_to_payload_row(row))

    await db.commit()
    return {"ok": True, "count": len(items), "items": items}


@router.get("/queue")
async def list_queue(
    status: str = Query("proposed"),
    campaign: Optional[str] = Query(None),
    property_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SeoPatchQueue).order_by(SeoPatchQueue.created_at.desc())
    count_query = select(func.count(SeoPatchQueue.id))

    if status != "all":
        query = query.where(SeoPatchQueue.status == status)
        count_query = count_query.where(SeoPatchQueue.status == status)
    if campaign:
        query = query.where(SeoPatchQueue.campaign == campaign)
        count_query = count_query.where(SeoPatchQueue.campaign == campaign)
    if property_id:
        query = query.where(SeoPatchQueue.property_id == property_id)
        count_query = count_query.where(SeoPatchQueue.property_id == property_id)

    query = query.limit(limit).offset(offset)
    rows = (await db.execute(query)).scalars().all()
    total = (await db.execute(count_query)).scalar() or 0

    return {"items": [_to_payload_row(r) for r in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/{patch_id:uuid}")
async def get_patch_detail(
    patch_id: UUID,
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoPatchQueue, patch_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO patch not found")
    return {"item": _to_payload_row(row)}


@router.put("/{patch_id:uuid}")
async def edit_patch(
    patch_id: UUID,
    body: EditProposalRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoPatchQueue, patch_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO patch not found")
    if row.status not in ("proposed", "needs_revision"):
        raise HTTPException(status_code=409, detail=f"Cannot edit patch in '{row.status}' state")

    updates = body.model_dump(exclude_unset=True)
    if "title" in updates:
        row.proposed_title = updates["title"] or ""
    if "meta_description" in updates:
        row.proposed_meta_description = updates["meta_description"] or ""
    if "h1" in updates:
        row.proposed_h1 = updates["h1"] or ""
    if "intro" in updates:
        row.proposed_intro = updates["intro"] or ""
    if "faq" in updates:
        row.proposed_faq = updates["faq"] or []
    if "json_ld" in updates:
        row.proposed_json_ld = updates["json_ld"] or {}

    row.reviewed_by = user.email
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload_row(row)}


@router.post("/{patch_id:uuid}/request-revision")
async def request_revision(
    patch_id: UUID,
    body: ReviewDecisionRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="review_note_required_for_revision")

    row = await db.get(SeoPatchQueue, patch_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO patch not found")
    if row.status not in ("proposed",):
        raise HTTPException(status_code=409, detail=f"Cannot request revision in '{row.status}' state")

    row.status = "needs_revision"
    row.review_note = note
    row.reviewed_by = user.email
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload_row(row)}


@router.post("/{patch_id:uuid}/approve")
async def approve_patch(
    patch_id: UUID,
    body: ReviewDecisionRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SeoPatchQueue, patch_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO patch not found")
    if row.status not in ("proposed", "needs_revision"):
        raise HTTPException(status_code=409, detail=f"Cannot approve patch in '{row.status}' state")

    result = await db.execute(
        select(SeoPatchQueue).where(
            SeoPatchQueue.property_id == row.property_id,
            SeoPatchQueue.campaign == row.campaign,
            SeoPatchQueue.status.in_(["approved", "deployed"]),
            SeoPatchQueue.id != row.id,
        )
    )
    previous = result.scalars().all()
    for prev in previous:
        prev.status = "superseded"
        prev.updated_at = datetime.utcnow()

    approved_payload = {
        "title": row.proposed_title,
        "meta_description": row.proposed_meta_description,
        "h1": row.proposed_h1,
        "intro": row.proposed_intro,
        "faq": row.proposed_faq or [],
        "json_ld": row.proposed_json_ld or {},
        "target_keyword": row.target_keyword,
        "campaign": row.campaign,
        "rubric_version": row.rubric_version,
    }
    row.status = "approved"
    row.reviewed_by = user.email
    row.review_note = (body.note or "").strip() or None
    row.approved_payload = approved_payload
    row.approved_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload_row(row)}


@router.post("/{patch_id:uuid}/reject")
async def reject_patch(
    patch_id: UUID,
    body: ReviewDecisionRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="review_note_required_for_reject")

    row = await db.get(SeoPatchQueue, patch_id)
    if not row:
        raise HTTPException(status_code=404, detail="SEO patch not found")
    if row.status not in ("proposed", "needs_revision"):
        raise HTTPException(status_code=409, detail=f"Cannot reject patch in '{row.status}' state")

    row.status = "rejected"
    row.reviewed_by = user.email
    row.review_note = note
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "item": _to_payload_row(row)}


@router.get("/live/property/{slug}")
async def get_live_payload_for_property(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    prop_result = await db.execute(select(Property).where(Property.slug == slug, Property.is_active.is_(True)))
    prop = prop_result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    result = await db.execute(
        select(SeoPatchQueue)
        .where(
            SeoPatchQueue.property_id == prop.id,
            SeoPatchQueue.status.in_(["approved", "deployed"]),
        )
        .order_by(SeoPatchQueue.approved_at.desc(), SeoPatchQueue.updated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No approved SEO payload for property")

    return {
        "property_slug": prop.slug,
        "property_name": prop.name,
        "payload": row.approved_payload or {},
    }


@router.get("/live/property/{slug}/debug")
async def get_live_payload_debug(
    slug: str,
    _user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prop_result = await db.execute(select(Property).where(Property.slug == slug, Property.is_active.is_(True)))
    prop = prop_result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    result = await db.execute(
        select(SeoPatchQueue)
        .where(
            SeoPatchQueue.property_id == prop.id,
            SeoPatchQueue.status.in_(["approved", "deployed"]),
        )
        .order_by(SeoPatchQueue.approved_at.desc(), SeoPatchQueue.updated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No approved SEO payload for property")

    return {
        "property_slug": prop.slug,
        "property_name": prop.name,
        "seo_patch": _to_payload_row(row),
    }


@router.get("/live/property-slugs")
async def list_live_slugs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Property.slug)
        .join(SeoPatchQueue, SeoPatchQueue.property_id == Property.id)
        .where(
            Property.is_active.is_(True),
            SeoPatchQueue.status.in_(["approved", "deployed"]),
        )
        .group_by(Property.slug)
        .order_by(Property.slug)
    )
    slugs = [row[0] for row in result.all()]
    return {"slugs": slugs}
