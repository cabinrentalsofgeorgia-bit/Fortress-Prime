"""Staff API for persisted NemoClaw / event-consumer AI insights.

Mounted at ``GET /api/admin/insights`` (see ``main.py``). Kept as ``admin_insights.py`` so it
does not shadow the existing ``backend.api.admin`` module (``admin.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS
from backend.core.database import get_db
from backend.models.ai_insight import AiInsight
from backend.models.staff import StaffUser

router = APIRouter()


class AiInsightRow(BaseModel):
    id: UUID
    task_id: str
    event_type: str
    reference_id: str
    insight_payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AiInsightListResponse(BaseModel):
    items: list[AiInsightRow] = Field(default_factory=list)
    count: int = 0


@router.get("/insights", response_model=AiInsightListResponse)
async def list_ai_insights(
    reference_id: str | None = Query(None, description="Filter by confirmation_code / property key / etc."),
    event_type: str | None = Query(None, description="Filter by Kafka topic or logical event type"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(CONTROL_ACCESS),
) -> AiInsightListResponse:
    """Return recent AI insights for Command Center surfaces (crog-ai.com)."""
    stmt = select(AiInsight).order_by(AiInsight.created_at.desc()).limit(limit)
    if reference_id is not None and reference_id.strip():
        stmt = stmt.where(AiInsight.reference_id == reference_id.strip())
    if event_type is not None and event_type.strip():
        stmt = stmt.where(AiInsight.event_type == event_type.strip())

    result = await db.execute(stmt)
    rows = result.scalars().all()
    items = [
        AiInsightRow(
            id=r.id,
            task_id=r.task_id,
            event_type=r.event_type,
            reference_id=r.reference_id,
            insight_payload=dict(r.insight_payload) if isinstance(r.insight_payload, dict) else {},
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AiInsightListResponse(items=items, count=len(items))
