"""
Phase 2 SEO patch API surface for Fortress Prime.
"""
from __future__ import annotations

import hmac
import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import RoleChecker, get_current_user
from backend.models import Property, SEOPatch, SEORubric, SeoPatchQueue
from backend.models.staff import StaffRole, StaffUser
from backend.schemas.seo_patch import SEOPatchCreate
from backend.services.openshell_audit import record_audit_event
from backend.vrs.infrastructure.seo_event_bus import (
    publish_deploy_event,
    publish_grade_request,
    publish_rewrite_request,
)

router = APIRouter()
internal_bearer = HTTPBearer(auto_error=False)
SEO_REVIEW_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])


class SEOPatchResponse(BaseModel):
    id: UUID
    property_id: UUID | None = None
    source_intelligence_id: UUID | None = None
    source_agent: str
    property_slug: str | None = None
    property_name: str | None = None
    rubric_id: UUID | None = None
    page_path: str
    patch_version: int
    status: str
    title: str | None = None
    meta_description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    h1_suggestion: str | None = None
    canonical_url: str | None = None
    jsonld_payload: dict[str, Any] | None = None
    alt_tags: dict[str, Any] | None = None
    godhead_score: float | None = None
    godhead_model: str | None = None
    godhead_feedback: dict[str, Any] | None = None
    grade_attempts: int
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    final_payload: dict[str, Any] | None = None
    deployed_at: datetime | None = None
    deploy_task_id: UUID | None = None
    deploy_status: str | None = None
    deploy_queued_at: datetime | None = None
    deploy_acknowledged_at: datetime | None = None
    deploy_attempts: int
    deploy_last_error: str | None = None
    deploy_last_http_status: int | None = None
    swarm_model: str | None = None
    swarm_node: str | None = None
    generation_ms: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SEORubricResponse(BaseModel):
    id: UUID
    keyword_cluster: str
    rubric_payload: dict[str, Any]
    source_model: str
    min_pass_score: float
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SEOPatchGradeRequest(BaseModel):
    godhead_score: float = Field(..., ge=0.0, le=1.0)
    godhead_model: str = Field(..., min_length=1, max_length=255)
    godhead_feedback: dict[str, Any] = Field(default_factory=dict)


class SeoProposalPayloadCompat(BaseModel):
    title: str
    meta_description: str
    h1: str
    intro: str
    faq: list[dict[str, Any]] = Field(default_factory=list)
    json_ld: dict[str, Any] = Field(default_factory=dict)


class SeoProposalGradingCompat(BaseModel):
    overall: float
    breakdown: dict[str, Any] = Field(default_factory=dict)


class SeoProposalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_type: str
    target_slug: str
    property_id: UUID | None = None
    target_keyword: str
    campaign: str = "default"
    rubric_version: str = "v1"
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    proposal: SeoProposalPayloadCompat
    grading: SeoProposalGradingCompat
    proposed_by: str = "dgx-swarm"
    proposal_run_id: str | None = None

    @model_validator(mode="after")
    def _normalize_target_fields(self) -> "SeoProposalRequest":
        normalized_type = str(self.target_type or "").strip().lower()
        normalized_slug = re.sub(r"[^a-z0-9-]+", "-", str(self.target_slug or "").strip().lower()).strip("-")
        if normalized_type not in {"property", "archive_review"}:
            raise ValueError("target_type must be 'property' or 'archive_review'")
        if not normalized_slug:
            raise ValueError("target_slug is required")
        self.target_type = normalized_type
        self.target_slug = normalized_slug
        return self


class SEORubricCreateRequest(BaseModel):
    keyword_cluster: str = Field(..., min_length=1, max_length=255)
    rubric_payload: dict[str, Any] = Field(default_factory=dict)
    source_model: str = Field(..., min_length=1, max_length=255)
    min_pass_score: float = Field(default=0.95, ge=0.0, le=1.0)
    status: str = Field(default="active", min_length=1, max_length=50)


class SEOPatchReviewApproveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    final_payload: "SEOPatchFinalPayload | None" = None


class SEOPatchFinalPayload(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=4000)
    og_title: str | None = Field(default=None, max_length=255)
    og_description: str | None = Field(default=None, max_length=4000)
    h1_suggestion: str | None = Field(default=None, max_length=255)
    jsonld: dict[str, Any] = Field(default_factory=dict)
    canonical_url: str | None = Field(default=None, max_length=2048)
    alt_tags: dict[str, Any] = Field(default_factory=dict)


class SEOPatchReviewEditRequest(BaseModel):
    final_payload: SEOPatchFinalPayload
    note: str | None = Field(default=None, max_length=2000)


class SEOPatchReviewRejectRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


class SEOPatchQueueListResponse(BaseModel):
    items: list[SEOPatchResponse]
    total: int
    offset: int
    limit: int


class SEOPatchQueueStatsResponse(BaseModel):
    drafted: int
    needs_rewrite: int
    pending_human: int
    deployed: int
    rejected: int
    total: int


class LiveSEOPayloadResponse(BaseModel):
    property_slug: str
    property_name: str
    page_path: str
    payload: dict[str, Any]
    deployed_at: datetime | None = None
    godhead_score: float | None = None


class LiveSEOBulkResponse(BaseModel):
    items: list[LiveSEOPayloadResponse]
    requested: int
    returned: int


class LiveLegacySEOPayloadResponse(BaseModel):
    target_type: str
    target_slug: str
    property_slug: str | None = None
    property_name: str | None = None
    payload: dict[str, Any]
    deployed_at: datetime | None = None
    approved_at: datetime | None = None


class LivePropertySlugListResponse(BaseModel):
    slugs: list[str]


def _source_hash(
    *,
    target_type: str,
    target_slug: str,
    campaign: str,
    rubric_version: str,
    source_snapshot: dict[str, Any],
) -> str:
    payload = {
        "target_type": str(target_type).strip().lower(),
        "target_slug": re.sub(r"[^a-z0-9-]+", "-", str(target_slug).strip().lower()).strip("-"),
        "campaign": str(campaign).strip().lower(),
        "rubric_version": str(rubric_version).strip().lower(),
        "source_snapshot": source_snapshot,
    }
    return hashlib.sha256(
        repr(payload).encode("utf-8")
    ).hexdigest()


async def require_swarm_seo_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(internal_bearer),
) -> str:
    expected_token = settings.swarm_seo_api_key.strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: SWARM_SEO_API_KEY not configured",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing machine bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(credentials.credentials, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid machine bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def _serialize_patch(
    patch: SEOPatch,
    *,
    property_slug: str | None = None,
    property_name: str | None = None,
) -> SEOPatchResponse:
    payload = SEOPatchResponse.model_validate(patch).model_dump()
    payload["property_slug"] = property_slug
    payload["property_name"] = property_name
    return SEOPatchResponse(**payload)


def _default_final_payload(patch: SEOPatch) -> dict[str, Any]:
    return {
        "title": patch.title,
        "meta_description": patch.meta_description,
        "og_title": patch.og_title,
        "og_description": patch.og_description,
        "h1_suggestion": patch.h1_suggestion,
        "jsonld": patch.jsonld_payload or {},
        "canonical_url": patch.canonical_url,
        "alt_tags": patch.alt_tags or {},
    }


def _normalize_legacy_overlay_payload(payload: dict[str, Any] | None, patch: SeoPatchQueue) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    title = source.get("title") or patch.proposed_title
    meta_description = source.get("meta_description") or patch.proposed_meta_description
    h1 = source.get("h1") or source.get("h1_suggestion") or patch.proposed_h1
    intro = source.get("intro") or patch.proposed_intro
    faq = source.get("faq") if isinstance(source.get("faq"), list) else (patch.proposed_faq or [])
    json_ld = source.get("json_ld") or source.get("jsonld") or patch.proposed_json_ld or {}
    normalized: dict[str, Any] = {
        "title": title,
        "meta_description": meta_description,
        "h1": h1,
        "intro": intro,
        "faq": faq,
        "json_ld": json_ld,
    }
    for optional_key in ("canonical_url", "og_title", "og_description", "alt_tags"):
        value = source.get(optional_key)
        if value is not None:
            normalized[optional_key] = value
    return normalized


def _snapshot_patch_state(patch: SEOPatch) -> dict[str, Any]:
    return {
        "page_path": patch.page_path,
        "patch_version": patch.patch_version,
        "status": patch.status,
        "title": patch.title,
        "meta_description": patch.meta_description,
        "og_title": patch.og_title,
        "og_description": patch.og_description,
        "jsonld_payload": patch.jsonld_payload,
        "canonical_url": patch.canonical_url,
        "h1_suggestion": patch.h1_suggestion,
        "alt_tags": patch.alt_tags,
        "godhead_score": patch.godhead_score,
        "godhead_model": patch.godhead_model,
        "godhead_feedback": patch.godhead_feedback,
        "reviewed_by": patch.reviewed_by,
        "reviewed_at": patch.reviewed_at,
        "final_payload": patch.final_payload,
        "deployed_at": patch.deployed_at,
        "deploy_task_id": patch.deploy_task_id,
        "deploy_status": patch.deploy_status,
        "deploy_queued_at": patch.deploy_queued_at,
        "deploy_acknowledged_at": patch.deploy_acknowledged_at,
        "deploy_attempts": patch.deploy_attempts,
        "deploy_last_error": patch.deploy_last_error,
        "deploy_last_http_status": patch.deploy_last_http_status,
        "swarm_model": patch.swarm_model,
        "swarm_node": patch.swarm_node,
        "generation_ms": patch.generation_ms,
    }


def _restore_patch_state(patch: SEOPatch, snapshot: dict[str, Any]) -> None:
    for key, value in snapshot.items():
        setattr(patch, key, value)


async def _resolve_property_for_patch(db: AsyncSession, property_id: UUID | None) -> Property | None:
    if property_id is None:
        return None
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


async def _resolve_rubric_id(db: AsyncSession, rubric_id: UUID | None) -> UUID:
    if rubric_id is not None:
        rubric = await db.get(SEORubric, rubric_id)
        if rubric is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found")
        return rubric.id

    rubric = (
        await db.execute(
            select(SEORubric)
            .where(SEORubric.status == "active")
            .order_by(SEORubric.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rubric is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active rubric available for SEO patch ingest",
        )
    return rubric.id


async def _load_patch_with_property(
    db: AsyncSession,
    patch_id: UUID,
) -> tuple[SEOPatch, str | None, str | None]:
    row = (
        await db.execute(
            select(SEOPatch, Property.slug, Property.name)
            .outerjoin(Property, Property.id == SEOPatch.property_id)
            .where(SEOPatch.id == patch_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO patch not found")
    patch, property_slug, property_name = row
    return patch, property_slug, property_name


async def _load_deployed_live_payload(
    db: AsyncSession,
    property_slug: str,
) -> LiveSEOPayloadResponse:
    normalized_slug = property_slug.strip().lower()
    property_row = (
        await db.execute(
            select(Property).where(
                Property.slug == normalized_slug,
                Property.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if property_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    patch = (
        await db.execute(
            select(SEOPatch)
            .where(
                SEOPatch.property_id == property_row.id,
                SEOPatch.status == "deployed",
            )
            .order_by(SEOPatch.deployed_at.desc(), SEOPatch.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if patch is None or patch.final_payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deployed SEO payload for property",
        )

    return LiveSEOPayloadResponse(
        property_slug=property_row.slug,
        property_name=property_row.name,
        page_path=patch.page_path,
        payload=patch.final_payload,
        deployed_at=patch.deployed_at,
        godhead_score=patch.godhead_score,
    )


async def _load_legacy_property_overlay(
    db: AsyncSession,
    property_slug: str,
) -> LiveLegacySEOPayloadResponse:
    normalized_slug = property_slug.strip().lower()
    row = (
        await db.execute(
            select(SeoPatchQueue, Property.slug, Property.name)
            .join(Property, Property.id == SeoPatchQueue.property_id)
            .where(
                SeoPatchQueue.target_type == "property",
                SeoPatchQueue.target_slug == normalized_slug,
                SeoPatchQueue.status.in_(("approved", "deployed")),
            )
            .order_by(SeoPatchQueue.deployed_at.desc(), SeoPatchQueue.approved_at.desc(), SeoPatchQueue.updated_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No legacy SEO overlay for property")

    patch, resolved_slug, property_name = row
    payload = _normalize_legacy_overlay_payload(patch.approved_payload, patch)
    return LiveLegacySEOPayloadResponse(
        target_type=patch.target_type,
        target_slug=patch.target_slug,
        property_slug=resolved_slug,
        property_name=property_name,
        payload=payload,
        deployed_at=patch.deployed_at,
        approved_at=patch.approved_at,
    )


async def _load_legacy_archive_overlay(
    db: AsyncSession,
    target_slug: str,
) -> LiveLegacySEOPayloadResponse:
    normalized_slug = target_slug.strip().lower()
    patch = (
        await db.execute(
            select(SeoPatchQueue)
            .where(
                SeoPatchQueue.target_type == "archive_review",
                SeoPatchQueue.target_slug == normalized_slug,
                SeoPatchQueue.status.in_(("approved", "deployed")),
            )
            .order_by(SeoPatchQueue.deployed_at.desc(), SeoPatchQueue.approved_at.desc(), SeoPatchQueue.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if patch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No legacy SEO overlay for archive slug")

    payload = _normalize_legacy_overlay_payload(patch.approved_payload, patch)
    return LiveLegacySEOPayloadResponse(
        target_type=patch.target_type,
        target_slug=patch.target_slug,
        payload=payload,
        deployed_at=patch.deployed_at,
        approved_at=patch.approved_at,
    )


async def _record_review_audit(
    *,
    action: str,
    patch: SEOPatch,
    request: Request,
    user: StaffUser,
    db: AsyncSession,
    note: str | None = None,
) -> None:
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action=action,
        resource_type="seo_patch",
        resource_id=str(patch.id),
        purpose="seo_phase2_review",
        tool_name="seo_patch_review",
        model_route="tool",
        request_id=request.headers.get("x-request-id"),
        db=db,
        metadata_json={
            "page_path": patch.page_path,
            "property_id": str(patch.property_id) if patch.property_id else None,
            "score": patch.godhead_score,
            "status": patch.status,
            "deploy_status": patch.deploy_status,
            "note": (note or "")[:500] or None,
        },
    )


async def _queue_deploy_event_for_patch(
    *,
    db: AsyncSession,
    patch: SEOPatch,
    request: Request,
    user: StaffUser,
    action: str,
) -> None:
    envelope = await publish_deploy_event(
        patch.id,
        metadata={
            "patch_version": patch.patch_version,
            "request_id": request.headers.get("x-request-id"),
            "reviewed_by": user.email,
        },
    )
    if envelope is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to enqueue deploy event")

    queued_at = datetime.now(timezone.utc)
    patch.deploy_task_id = envelope.task_id
    patch.deploy_status = "queued"
    patch.deploy_queued_at = queued_at
    patch.deploy_acknowledged_at = None
    patch.deploy_attempts = 0
    patch.deploy_last_error = None
    patch.deploy_last_http_status = None
    await db.commit()
    await db.refresh(patch)

    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action=action,
        resource_type="seo_patch",
        resource_id=str(patch.id),
        purpose="seo_phase2_deploy",
        tool_name="seo_deploy_event_bus",
        model_route="tool",
        request_id=request.headers.get("x-request-id"),
        db=db,
        metadata_json={
            "task_id": str(envelope.task_id),
            "page_path": patch.page_path,
            "property_id": str(patch.property_id) if patch.property_id else None,
            "deploy_status": patch.deploy_status,
        },
    )


@router.post("/patches", response_model=SEOPatchResponse, status_code=status.HTTP_201_CREATED)
async def create_patch(
    payload: SEOPatchCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_swarm_seo_bearer),
) -> SEOPatchResponse:
    prop = await _resolve_property_for_patch(db, payload.property_id)
    rubric_id = await _resolve_rubric_id(db, payload.rubric_id)

    patch = SEOPatch(
        property_id=payload.property_id,
        rubric_id=rubric_id,
        source_agent="seo_patch_api",
        page_path=payload.page_path,
        title=payload.title,
        meta_description=payload.meta_description,
        og_title=payload.og_title,
        og_description=payload.og_description,
        jsonld_payload=payload.jsonld_payload,
        canonical_url=payload.canonical_url,
        h1_suggestion=payload.h1_suggestion,
        alt_tags=payload.alt_tags,
        swarm_model=payload.swarm_model,
        swarm_node=payload.swarm_node,
        generation_ms=payload.generation_ms,
        status="drafted",
    )
    db.add(patch)
    await db.commit()
    await db.refresh(patch)

    if not await publish_grade_request(patch.id):
        await db.delete(patch)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to enqueue grade request")

    await record_audit_event(
        action="seo.patch.ingested",
        resource_type="seo_patch",
        resource_id=str(patch.id),
        purpose="seo_phase2_ingest",
        tool_name="seo_patch_ingest",
        model_route=patch.swarm_model or "unknown",
        request_id=request.headers.get("x-request-id"),
        metadata_json={"property_id": str(patch.property_id) if patch.property_id else None},
    )
    return _serialize_patch(
        patch,
        property_slug=prop.slug if prop else None,
        property_name=prop.name if prop else None,
    )


@router.post("/patches/{patch_id}/rewrite", response_model=SEOPatchResponse)
async def rewrite_patch(
    patch_id: UUID,
    payload: SEOPatchCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_swarm_seo_bearer),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    if patch.status != "needs_rewrite":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patch is not in a rewrite state. Current status: {patch.status}",
        )
    if payload.property_id is not None and payload.property_id != patch.property_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rewrite property_id does not match patch")
    if payload.rubric_id is not None and payload.rubric_id != patch.rubric_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rewrite rubric_id does not match patch")

    snapshot = _snapshot_patch_state(patch)
    patch.page_path = payload.page_path
    patch.title = payload.title
    patch.meta_description = payload.meta_description
    patch.og_title = payload.og_title
    patch.og_description = payload.og_description
    patch.jsonld_payload = payload.jsonld_payload
    patch.canonical_url = payload.canonical_url
    patch.h1_suggestion = payload.h1_suggestion
    patch.alt_tags = payload.alt_tags
    patch.swarm_model = payload.swarm_model
    patch.swarm_node = payload.swarm_node
    patch.generation_ms = payload.generation_ms
    patch.patch_version += 1
    patch.status = "drafted"
    patch.godhead_score = None
    patch.godhead_model = None
    patch.godhead_feedback = None
    patch.reviewed_by = None
    patch.reviewed_at = None
    patch.final_payload = None
    patch.deployed_at = None
    patch.deploy_task_id = None
    patch.deploy_status = None
    patch.deploy_queued_at = None
    patch.deploy_acknowledged_at = None
    patch.deploy_attempts = 0
    patch.deploy_last_error = None
    patch.deploy_last_http_status = None
    await db.commit()
    await db.refresh(patch)

    if not await publish_grade_request(patch.id):
        _restore_patch_state(patch, snapshot)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to enqueue grade request")

    await record_audit_event(
        action="seo.patch.rewritten",
        resource_type="seo_patch",
        resource_id=str(patch.id),
        purpose="seo_phase2_rewrite",
        tool_name="seo_patch_rewrite",
        model_route=patch.swarm_model or "unknown",
        request_id=request.headers.get("x-request-id"),
        metadata_json={"patch_version": patch.patch_version},
    )
    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.post("/patches/{patch_id}/grade", response_model=SEOPatchResponse)
async def grade_patch(
    patch_id: UUID,
    body: SEOPatchGradeRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_swarm_seo_bearer),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    rubric = await db.get(SEORubric, patch.rubric_id) if patch.rubric_id else None
    threshold = max(
        float(settings.seo_godhead_min_score),
        float(rubric.min_pass_score) if rubric else 0.0,
    )

    patch.grade_attempts += 1
    patch.godhead_score = body.godhead_score
    patch.godhead_model = body.godhead_model.strip()
    patch.godhead_feedback = body.godhead_feedback

    enqueue_rewrite = False
    if body.godhead_score >= threshold:
        patch.status = "pending_human"
    elif patch.grade_attempts < settings.seo_max_rewrite_attempts:
        patch.status = "needs_rewrite"
        enqueue_rewrite = True
    else:
        patch.status = "pending_human"

    await db.commit()
    await db.refresh(patch)

    if enqueue_rewrite and not await publish_rewrite_request(patch.id, body.godhead_feedback):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to enqueue rewrite request")

    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.post("/rubrics", response_model=SEORubricResponse, status_code=status.HTTP_201_CREATED)
async def create_rubric(
    body: SEORubricCreateRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_swarm_seo_bearer),
) -> SEORubricResponse:
    rubric = SEORubric(
        keyword_cluster=body.keyword_cluster.strip(),
        rubric_payload=body.rubric_payload,
        source_model=body.source_model.strip(),
        min_pass_score=body.min_pass_score,
        status=body.status.strip(),
    )
    db.add(rubric)
    await db.commit()
    await db.refresh(rubric)
    return SEORubricResponse.model_validate(rubric)


@router.get("/rubrics", response_model=list[SEORubricResponse])
async def list_rubrics(
    status_filter: str = Query("active", alias="status"),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_swarm_seo_bearer),
) -> list[SEORubricResponse]:
    rubrics = (
        await db.execute(
            select(SEORubric)
            .where(SEORubric.status == status_filter)
            .order_by(SEORubric.created_at.desc())
        )
    ).scalars().all()
    return [SEORubricResponse.model_validate(rubric) for rubric in rubrics]


@router.get("/queue", response_model=SEOPatchQueueListResponse)
async def list_queue(
    status_filter: str = Query("pending_human", alias="status"),
    property_slug: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchQueueListResponse:
    stmt = select(SEOPatch, Property.slug, Property.name).outerjoin(Property, Property.id == SEOPatch.property_id)
    count_stmt = select(func.count(SEOPatch.id))

    if status_filter != "all":
        stmt = stmt.where(SEOPatch.status == status_filter)
        count_stmt = count_stmt.where(SEOPatch.status == status_filter)
    if property_slug:
        normalized_slug = property_slug.strip().lower()
        stmt = stmt.where(Property.slug == normalized_slug)
        count_stmt = count_stmt.join(Property, Property.id == SEOPatch.property_id).where(Property.slug == normalized_slug)

    stmt = stmt.order_by(SEOPatch.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    total = (await db.execute(count_stmt)).scalar_one()

    return SEOPatchQueueListResponse(
        items=[
            _serialize_patch(patch, property_slug=row_property_slug, property_name=row_property_name)
            for patch, row_property_slug, row_property_name in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/queue/stats", response_model=SEOPatchQueueStatsResponse)
async def queue_stats(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchQueueStatsResponse:
    rows = (await db.execute(select(SEOPatch.status, func.count(SEOPatch.id)).group_by(SEOPatch.status))).all()
    counts = {row_status: row_count for row_status, row_count in rows}
    return SEOPatchQueueStatsResponse(
        drafted=counts.get("drafted", 0),
        needs_rewrite=counts.get("needs_rewrite", 0),
        pending_human=counts.get("pending_human", 0),
        deployed=counts.get("deployed", 0),
        rejected=counts.get("rejected", 0),
        total=sum(counts.values()),
    )


@router.get("/queue/{patch_id}", response_model=SEOPatchResponse)
async def get_queue_patch(
    patch_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.post("/queue/{patch_id}/approve", response_model=SEOPatchResponse)
async def approve_patch(
    patch_id: UUID,
    body: SEOPatchReviewApproveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    if patch.status != "pending_human":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot approve patch in '{patch.status}' state")

    snapshot = _snapshot_patch_state(patch)
    now = datetime.now(timezone.utc)
    patch.status = "approved"
    patch.reviewed_by = user.email
    patch.reviewed_at = now
    patch.deployed_at = None
    patch.final_payload = (
        body.final_payload.model_dump(mode="json")
        if body.final_payload is not None
        else _default_final_payload(patch)
    )
    patch.deploy_task_id = None
    patch.deploy_status = None
    patch.deploy_queued_at = None
    patch.deploy_acknowledged_at = None
    patch.deploy_attempts = 0
    patch.deploy_last_error = None
    patch.deploy_last_http_status = None
    await db.commit()
    await db.refresh(patch)

    try:
        await _queue_deploy_event_for_patch(
            db=db,
            patch=patch,
            request=request,
            user=user,
            action="seo.patch.deploy_queued",
        )
    except HTTPException:
        _restore_patch_state(patch, snapshot)
        await db.commit()
        raise

    await _record_review_audit(
        action="seo.patch.approved",
        patch=patch,
        request=request,
        user=user,
        db=db,
        note=body.note,
    )
    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.post("/queue/{patch_id}/edit", response_model=SEOPatchResponse)
async def edit_patch(
    patch_id: UUID,
    body: SEOPatchReviewEditRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    if patch.status != "pending_human":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot edit patch in '{patch.status}' state")

    snapshot = _snapshot_patch_state(patch)
    now = datetime.now(timezone.utc)
    patch.status = "edited"
    patch.reviewed_by = user.email
    patch.reviewed_at = now
    patch.deployed_at = None
    patch.final_payload = body.final_payload.model_dump(mode="json")
    patch.deploy_task_id = None
    patch.deploy_status = None
    patch.deploy_queued_at = None
    patch.deploy_acknowledged_at = None
    patch.deploy_attempts = 0
    patch.deploy_last_error = None
    patch.deploy_last_http_status = None
    await db.commit()
    await db.refresh(patch)

    try:
        await _queue_deploy_event_for_patch(
            db=db,
            patch=patch,
            request=request,
            user=user,
            action="seo.patch.deploy_queued",
        )
    except HTTPException:
        _restore_patch_state(patch, snapshot)
        await db.commit()
        raise

    await _record_review_audit(
        action="seo.patch.edited",
        patch=patch,
        request=request,
        user=user,
        db=db,
        note=body.note,
    )
    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.post("/queue/{patch_id}/reject", response_model=SEOPatchResponse)
async def reject_patch(
    patch_id: UUID,
    body: SEOPatchReviewRejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(SEO_REVIEW_ACCESS),
) -> SEOPatchResponse:
    patch, property_slug, property_name = await _load_patch_with_property(db, patch_id)
    if patch.status != "pending_human":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot reject patch in '{patch.status}' state")

    patch.status = "rejected"
    patch.reviewed_by = user.email
    patch.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(patch)

    await _record_review_audit(
        action="seo.patch.rejected",
        patch=patch,
        request=request,
        user=user,
        db=db,
        note=body.note,
    )
    return _serialize_patch(patch, property_slug=property_slug, property_name=property_name)


@router.get("/live/bulk", response_model=LiveSEOBulkResponse)
async def get_live_payload_bulk(
    property_slug: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> LiveSEOBulkResponse:
    requested_slugs = [slug.strip().lower() for slug in (property_slug or []) if slug.strip()]
    if not requested_slugs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one property_slug query parameter is required",
        )

    items: list[LiveSEOPayloadResponse] = []
    for slug in requested_slugs:
        try:
            items.append(await _load_deployed_live_payload(db, slug))
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise

    return LiveSEOBulkResponse(items=items, requested=len(requested_slugs), returned=len(items))


@router.get("/live/property-slugs", response_model=LivePropertySlugListResponse)
async def get_live_property_slugs(
    db: AsyncSession = Depends(get_db),
) -> LivePropertySlugListResponse:
    rows = (
        await db.execute(
            select(Property.slug)
            .join(SEOPatch, SEOPatch.property_id == Property.id)
            .where(
                Property.is_active.is_(True),
                SEOPatch.status == "deployed",
            )
            .distinct()
            .order_by(Property.slug.asc())
        )
    ).scalars().all()
    return LivePropertySlugListResponse(slugs=[slug for slug in rows if slug])


@router.get("/live/property/{property_slug}", response_model=LiveLegacySEOPayloadResponse)
async def get_live_property_overlay(
    property_slug: str,
    db: AsyncSession = Depends(get_db),
) -> LiveLegacySEOPayloadResponse:
    return await _load_legacy_property_overlay(db, property_slug)


@router.get("/live/archive/{target_slug}", response_model=LiveLegacySEOPayloadResponse)
async def get_live_archive_overlay(
    target_slug: str,
    db: AsyncSession = Depends(get_db),
) -> LiveLegacySEOPayloadResponse:
    return await _load_legacy_archive_overlay(db, target_slug)


@router.get("/live/{property_slug}", response_model=LiveSEOPayloadResponse)
async def get_live_payload(
    property_slug: str,
    db: AsyncSession = Depends(get_db),
) -> LiveSEOPayloadResponse:
    return await _load_deployed_live_payload(db, property_slug)


# ── Pipeline stats (internal dashboard KPIs) ─────────────────────────────────

class SEOPipelineStatsResponse(BaseModel):
    """Real-time SEO pipeline counters for the Command Center dashboard."""
    # Patch queue counts
    drafts_created: int
    pending_review: int
    deployed_count: int
    needs_rewrite: int
    # Rubric health
    active_rubrics: int
    # Property coverage
    properties_with_draft: int
    properties_without_draft: int
    total_active_properties: int
    # Aggregate quality
    avg_godhead_score: float | None


@router.get("/pipeline-stats", response_model=SEOPipelineStatsResponse)
async def seo_pipeline_stats(db: AsyncSession = Depends(get_db)) -> SEOPipelineStatsResponse:
    """
    Returns internal SEO pipeline metrics for Command Center KPI cards.
    No auth required — counts only, no PII.
    """
    # Patch status counts
    status_rows = (
        await db.execute(
            select(SEOPatch.status, func.count(SEOPatch.id)).group_by(SEOPatch.status)
        )
    ).all()
    counts: dict[str, int] = {row_status: row_count for row_status, row_count in status_rows}

    # Active rubrics
    active_rubrics = (
        await db.execute(select(func.count(SEORubric.id)).where(SEORubric.status == "active"))
    ).scalar_one() or 0

    # Property coverage — active properties
    total_active_props = (
        await db.execute(
            select(func.count(Property.id)).where(Property.is_active.is_(True))
        )
    ).scalar_one() or 0

    ACTIVE_STATUSES = ("drafted", "grading", "needs_rewrite", "pending_human", "deployed")
    props_with_draft = (
        await db.execute(
            select(func.count(SEOPatch.property_id.distinct())).where(
                SEOPatch.status.in_(ACTIVE_STATUSES),
                SEOPatch.property_id.isnot(None),
            )
        )
    ).scalar_one() or 0

    # Average godhead score for deployed patches
    avg_score_row = (
        await db.execute(
            select(func.avg(SEOPatch.godhead_score)).where(
                SEOPatch.status == "deployed",
                SEOPatch.godhead_score.isnot(None),
            )
        )
    ).scalar_one()
    avg_score = round(float(avg_score_row), 3) if avg_score_row is not None else None

    return SEOPipelineStatsResponse(
        drafts_created=counts.get("drafted", 0) + counts.get("grading", 0)
            + counts.get("needs_rewrite", 0) + counts.get("pending_human", 0)
            + counts.get("deployed", 0) + counts.get("rejected", 0),
        pending_review=counts.get("pending_human", 0),
        deployed_count=counts.get("deployed", 0),
        needs_rewrite=counts.get("needs_rewrite", 0),
        active_rubrics=int(active_rubrics),
        properties_with_draft=int(props_with_draft),
        properties_without_draft=max(0, int(total_active_props) - int(props_with_draft)),
        total_active_properties=int(total_active_props),
        avg_godhead_score=avg_score,
    )
