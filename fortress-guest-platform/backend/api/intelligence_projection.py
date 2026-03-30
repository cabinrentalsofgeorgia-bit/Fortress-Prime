"""Public contextual projection API for property-targeted Scout findings."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.intelligence_projection import build_property_context_projection

router = APIRouter()


class PropertyContextItemPayload(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    market: str
    locality: str | None = None
    confidence_score: float | None = None
    query_topic: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    target_tags: list[str] = Field(default_factory=list)
    discovered_at: datetime


class PropertyContextProjectionPayload(BaseModel):
    property_id: str
    property_slug: str
    property_name: str
    items: list[PropertyContextItemPayload] = Field(default_factory=list)
    generated_at: str


@router.get("/property/{slug}", response_model=PropertyContextProjectionPayload)
async def get_property_context_projection(
    slug: str,
    limit: int = Query(default=3, ge=1, le=6),
    db: AsyncSession = Depends(get_db),
) -> PropertyContextProjectionPayload:
    projection = await build_property_context_projection(db, property_slug=slug, limit=limit)
    if projection is None:
        raise HTTPException(status_code=404, detail="Property not found")

    return PropertyContextProjectionPayload(
        **projection,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
