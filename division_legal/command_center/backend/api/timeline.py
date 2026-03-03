"""
Timeline API — running record of events, actions, notes on matters.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from pydantic import BaseModel

from backend.core.database import get_db
from backend.models.timeline import TimelineEntry

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class TimelineCreate(BaseModel):
    matter_id: UUID
    entry_type: str       # note, action, decision, filing, correspondence, research, payment, milestone
    title: str
    body: Optional[str] = None
    entered_by: str = "owner"
    importance: str = "normal"
    related_meeting_id: Optional[UUID] = None
    related_attorney_id: Optional[UUID] = None
    document_ref: Optional[str] = None
    tags: Optional[List[str]] = None


class TimelineUpdate(BaseModel):
    entry_type: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    importance: Optional[str] = None
    document_ref: Optional[str] = None
    tags: Optional[List[str]] = None


class TimelineResponse(BaseModel):
    id: UUID
    matter_id: UUID
    entry_type: str
    title: str
    body: Optional[str] = None
    entered_by: Optional[str] = "owner"
    importance: Optional[str] = "normal"
    related_meeting_id: Optional[UUID] = None
    related_attorney_id: Optional[UUID] = None
    attorney_name: Optional[str] = None
    document_ref: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_response(t: TimelineEntry) -> TimelineResponse:
    attorney_name = None
    if t.attorney:
        attorney_name = f"{t.attorney.first_name} {t.attorney.last_name}"
    return TimelineResponse(
        id=t.id,
        matter_id=t.matter_id,
        entry_type=t.entry_type,
        title=t.title,
        body=t.body,
        entered_by=t.entered_by,
        importance=t.importance,
        related_meeting_id=t.related_meeting_id,
        related_attorney_id=t.related_attorney_id,
        attorney_name=attorney_name,
        document_ref=t.document_ref,
        tags=t.tags,
        created_at=t.created_at,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[TimelineResponse])
async def list_timeline(
    matter_id: Optional[UUID] = Query(None),
    entry_type: Optional[str] = Query(None),
    importance: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(TimelineEntry).order_by(desc(TimelineEntry.created_at))
    if matter_id:
        query = query.where(TimelineEntry.matter_id == matter_id)
    if entry_type:
        query = query.where(TimelineEntry.entry_type == entry_type)
    if importance:
        query = query.where(TimelineEntry.importance == importance)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(t) for t in result.scalars().all()]


@router.get("/{entry_id}", response_model=TimelineResponse)
async def get_entry(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    t = await db.get(TimelineEntry, entry_id)
    if not t:
        raise HTTPException(404, "Timeline entry not found")
    return _to_response(t)


@router.post("/", response_model=TimelineResponse, status_code=201)
async def create_entry(data: TimelineCreate, db: AsyncSession = Depends(get_db)):
    entry = TimelineEntry(**data.model_dump(exclude_unset=True))
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _to_response(entry)


@router.patch("/{entry_id}", response_model=TimelineResponse)
async def update_entry(entry_id: UUID, data: TimelineUpdate, db: AsyncSession = Depends(get_db)):
    entry = await db.get(TimelineEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Timeline entry not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.flush()
    await db.refresh(entry)
    return _to_response(entry)


@router.delete("/{entry_id}")
async def delete_entry(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    entry = await db.get(TimelineEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Timeline entry not found")
    await db.delete(entry)
    return {"status": "deleted", "id": str(entry_id)}
