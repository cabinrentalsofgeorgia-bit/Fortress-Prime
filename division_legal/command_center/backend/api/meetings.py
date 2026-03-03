"""
Meetings API — CRUD for meetings, calls, and consultations.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, desc, func
from pydantic import BaseModel

from backend.core.database import get_db
from backend.models.meeting import Meeting
from backend.models.timeline import TimelineEntry

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    matter_id: Optional[UUID] = None
    attorney_id: Optional[UUID] = None
    title: str
    meeting_type: str = "in_person"
    meeting_date: datetime
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    action_items: Optional[str] = None
    key_decisions: Optional[str] = None
    documents_discussed: Optional[str] = None
    billable: bool = False
    cost: Optional[Decimal] = None
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None
    tags: Optional[List[str]] = None


class MeetingUpdate(BaseModel):
    matter_id: Optional[UUID] = None
    attorney_id: Optional[UUID] = None
    title: Optional[str] = None
    meeting_type: Optional[str] = None
    meeting_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    action_items: Optional[str] = None
    key_decisions: Optional[str] = None
    documents_discussed: Optional[str] = None
    billable: Optional[bool] = None
    cost: Optional[Decimal] = None
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None
    tags: Optional[List[str]] = None


class MeetingResponse(BaseModel):
    id: UUID
    matter_id: Optional[UUID] = None
    matter_title: Optional[str] = None
    attorney_id: Optional[UUID] = None
    attorney_name: Optional[str] = None
    title: str
    meeting_type: str
    meeting_date: datetime
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    action_items: Optional[str] = None
    key_decisions: Optional[str] = None
    documents_discussed: Optional[str] = None
    billable: bool = False
    cost: Optional[Decimal] = None
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_response(m: Meeting) -> MeetingResponse:
    matter_title = m.matter.title if m.matter else None
    attorney_name = None
    if m.attorney:
        attorney_name = f"{m.attorney.first_name} {m.attorney.last_name}"
    return MeetingResponse(
        id=m.id,
        matter_id=m.matter_id,
        matter_title=matter_title,
        attorney_id=m.attorney_id,
        attorney_name=attorney_name,
        title=m.title,
        meeting_type=m.meeting_type,
        meeting_date=m.meeting_date,
        duration_minutes=m.duration_minutes,
        location=m.location,
        attendees=m.attendees,
        summary=m.summary,
        action_items=m.action_items,
        key_decisions=m.key_decisions,
        documents_discussed=m.documents_discussed,
        billable=m.billable,
        cost=m.cost,
        follow_up_date=m.follow_up_date,
        follow_up_notes=m.follow_up_notes,
        tags=m.tags,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[MeetingResponse])
async def list_meetings(
    search: Optional[str] = Query(None),
    matter_id: Optional[UUID] = Query(None),
    attorney_id: Optional[UUID] = Query(None),
    meeting_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Meeting).order_by(desc(Meeting.meeting_date))
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            Meeting.title.ilike(term),
            Meeting.summary.ilike(term),
            Meeting.attendees.ilike(term),
        ))
    if matter_id:
        query = query.where(Meeting.matter_id == matter_id)
    if attorney_id:
        query = query.where(Meeting.attorney_id == attorney_id)
    if meeting_type:
        query = query.where(Meeting.meeting_type == meeting_type)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(m) for m in result.scalars().all()]


@router.get("/upcoming")
async def upcoming_meetings(days: int = Query(30, ge=1, le=90), db: AsyncSession = Depends(get_db)):
    from datetime import timedelta
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    query = (
        select(Meeting)
        .where(Meeting.meeting_date >= now)
        .where(Meeting.meeting_date <= cutoff)
        .order_by(Meeting.meeting_date)
    )
    result = await db.execute(query)
    return [_to_response(m) for m in result.scalars().all()]


@router.get("/follow-ups")
async def follow_ups_due(db: AsyncSession = Depends(get_db)):
    today = date.today()
    query = (
        select(Meeting)
        .where(Meeting.follow_up_date != None)
        .where(Meeting.follow_up_date <= today)
        .order_by(Meeting.follow_up_date)
    )
    result = await db.execute(query)
    return [_to_response(m) for m in result.scalars().all()]


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(meeting_id: UUID, db: AsyncSession = Depends(get_db)):
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    return _to_response(m)


@router.post("/", response_model=MeetingResponse, status_code=201)
async def create_meeting(data: MeetingCreate, db: AsyncSession = Depends(get_db)):
    meeting = Meeting(**data.model_dump(exclude_unset=True))
    db.add(meeting)
    await db.flush()
    await db.refresh(meeting)

    if meeting.matter_id and meeting.summary:
        entry = TimelineEntry(
            matter_id=meeting.matter_id,
            entry_type="meeting",
            title=f"Meeting: {meeting.title}",
            body=meeting.summary,
            related_meeting_id=meeting.id,
            related_attorney_id=meeting.attorney_id,
            importance="normal",
        )
        db.add(entry)
        await db.flush()

    return _to_response(meeting)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(meeting_id: UUID, data: MeetingUpdate, db: AsyncSession = Depends(get_db)):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(meeting, field, value)
    await db.flush()
    await db.refresh(meeting)
    return _to_response(meeting)


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: UUID, db: AsyncSession = Depends(get_db)):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    await db.delete(meeting)
    return {"status": "deleted", "id": str(meeting_id)}
