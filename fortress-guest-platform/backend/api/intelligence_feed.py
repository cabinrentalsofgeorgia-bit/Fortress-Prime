"""Staff-facing market intelligence feed API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.staff import StaffRole, StaffUser
from backend.services.async_jobs import extract_request_actor
from backend.services.intelligence_projection import build_intelligence_feed_snapshot
from backend.services.research_scout import ResearchScoutService
from backend.services.scout_action_router import research_scout_action_router

router = APIRouter()
scout_service = ResearchScoutService()


class IntelligenceTargetPropertyPayload(BaseModel):
    id: str
    slug: str
    name: str


class IntelligenceFeedItemPayload(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    market: str
    locality: str | None = None
    confidence_score: float | None = None
    dedupe_hash: str
    query_topic: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    target_tags: list[str] = Field(default_factory=list)
    targeted_properties: list[IntelligenceTargetPropertyPayload] = Field(default_factory=list)
    seo_patch_ids: list[str] = Field(default_factory=list)
    seo_patch_statuses: list[str] = Field(default_factory=list)
    pricing_signal_ids: list[str] = Field(default_factory=list)
    pricing_signal_statuses: list[str] = Field(default_factory=list)
    discovered_at: datetime
    created_at: datetime


class IntelligenceFeedPayload(BaseModel):
    items: list[IntelligenceFeedItemPayload]
    generated_at: str


class IntelligenceScoutRunPayload(BaseModel):
    market: str
    scout_run_key: str
    inserted_count: int
    duplicate_count: int
    inserted_entry_ids: list[str] = Field(default_factory=list)
    topics: list[dict[str, Any]]
    actions: dict[str, Any] = Field(default_factory=dict)
    generated_at: str


@router.get("/latest", response_model=IntelligenceFeedPayload)
async def list_intelligence_feed(
    _: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])),
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> IntelligenceFeedPayload:
    rows = await build_intelligence_feed_snapshot(db, limit=limit, category=category)
    return IntelligenceFeedPayload(
        items=[IntelligenceFeedItemPayload.model_validate(entry) for entry in rows],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/observe", response_model=IntelligenceScoutRunPayload)
async def trigger_research_scout(
    user: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])),
    db: AsyncSession = Depends(get_db),
) -> IntelligenceScoutRunPayload:
    actor = extract_request_actor(getattr(user, "email", None), getattr(user, "email", None))
    result = await scout_service.run_cycle(db, scout_run_key=f"manual:{actor}")
    result["actions"] = await research_scout_action_router.route_inserted_findings(
        db,
        inserted_entry_ids=list(result.get("inserted_entry_ids") or []),
    )
    return IntelligenceScoutRunPayload.model_validate(result)
