"""
Matters API — CRUD for legal matters, cases, disputes, and projects.
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
from backend.models.matter import Matter
from backend.models.timeline import TimelineEntry

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class MatterCreate(BaseModel):
    title: str
    reference_code: Optional[str] = None
    category: str
    status: str = "open"
    priority: str = "normal"
    description: Optional[str] = None
    attorney_id: Optional[UUID] = None
    opposing_party: Optional[str] = None
    opposing_counsel: Optional[str] = None
    amount_at_stake: Optional[Decimal] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    tags: Optional[List[str]] = None


class MatterUpdate(BaseModel):
    title: Optional[str] = None
    reference_code: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    description: Optional[str] = None
    attorney_id: Optional[UUID] = None
    opposing_party: Optional[str] = None
    opposing_counsel: Optional[str] = None
    amount_at_stake: Optional[Decimal] = None
    outcome: Optional[str] = None
    outcome_date: Optional[date] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    tags: Optional[List[str]] = None


class MatterResponse(BaseModel):
    id: UUID
    title: str
    reference_code: Optional[str] = None
    category: str
    status: str
    priority: str
    description: Optional[str] = None
    attorney_id: Optional[UUID] = None
    attorney_name: Optional[str] = None
    opposing_party: Optional[str] = None
    opposing_counsel: Optional[str] = None
    amount_at_stake: Optional[Decimal] = None
    outcome: Optional[str] = None
    outcome_date: Optional[date] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    tags: Optional[List[str]] = None
    meeting_count: int = 0
    timeline_count: int = 0
    document_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MatterDetail(MatterResponse):
    timeline: List[dict] = []
    meetings: List[dict] = []
    documents: List[dict] = []


def _to_response(m: Matter) -> MatterResponse:
    attorney_name = None
    if m.attorney:
        attorney_name = f"{m.attorney.first_name} {m.attorney.last_name}"
    return MatterResponse(
        id=m.id,
        title=m.title,
        reference_code=m.reference_code,
        category=m.category,
        status=m.status,
        priority=m.priority,
        description=m.description,
        attorney_id=m.attorney_id,
        attorney_name=attorney_name,
        opposing_party=m.opposing_party,
        opposing_counsel=m.opposing_counsel,
        amount_at_stake=m.amount_at_stake,
        outcome=m.outcome,
        outcome_date=m.outcome_date,
        next_action=m.next_action,
        next_action_date=m.next_action_date,
        tags=m.tags,
        meeting_count=len(m.meetings) if m.meetings else 0,
        timeline_count=len(m.timeline) if m.timeline else 0,
        document_count=len(m.documents) if m.documents else 0,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _to_detail(m: Matter) -> MatterDetail:
    base = _to_response(m)
    timeline_list = []
    if m.timeline:
        for t in m.timeline:
            timeline_list.append({
                "id": str(t.id),
                "entry_type": t.entry_type,
                "title": t.title,
                "body": t.body,
                "entered_by": t.entered_by,
                "importance": t.importance,
                "tags": t.tags,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
    meetings_list = []
    if m.meetings:
        for mt in sorted(m.meetings, key=lambda x: x.meeting_date or datetime.min, reverse=True):
            attorney_name = None
            if mt.attorney:
                attorney_name = f"{mt.attorney.first_name} {mt.attorney.last_name}"
            meetings_list.append({
                "id": str(mt.id),
                "title": mt.title,
                "meeting_type": mt.meeting_type,
                "meeting_date": mt.meeting_date.isoformat() if mt.meeting_date else None,
                "duration_minutes": mt.duration_minutes,
                "attorney_name": attorney_name,
                "summary": mt.summary,
                "action_items": mt.action_items,
            })
    docs_list = []
    if m.documents:
        for d in m.documents:
            docs_list.append({
                "id": str(d.id),
                "title": d.title,
                "doc_type": d.doc_type,
                "file_path": d.file_path,
                "description": d.description,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            })
    return MatterDetail(
        **base.model_dump(),
        timeline=timeline_list,
        meetings=meetings_list,
        documents=docs_list,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[MatterResponse])
async def list_matters(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    attorney_id: Optional[UUID] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Matter).order_by(desc(Matter.updated_at))
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            Matter.title.ilike(term),
            Matter.reference_code.ilike(term),
            Matter.description.ilike(term),
            Matter.opposing_party.ilike(term),
        ))
    if status:
        query = query.where(Matter.status == status)
    if category:
        query = query.where(Matter.category == category)
    if priority:
        query = query.where(Matter.priority == priority)
    if attorney_id:
        query = query.where(Matter.attorney_id == attorney_id)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(m) for m in result.scalars().all()]


@router.get("/stats")
async def matter_stats(db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count(Matter.id)))
    open_q = await db.execute(select(func.count(Matter.id)).where(Matter.status.in_(["open", "active"])))
    critical = await db.execute(select(func.count(Matter.id)).where(Matter.priority == "critical"))
    return {
        "total": total.scalar_one(),
        "open": open_q.scalar_one(),
        "critical": critical.scalar_one(),
    }


@router.get("/{matter_id}", response_model=MatterDetail)
async def get_matter(matter_id: UUID, db: AsyncSession = Depends(get_db)):
    m = await db.get(Matter, matter_id)
    if not m:
        raise HTTPException(404, "Matter not found")
    return _to_detail(m)


@router.post("/", response_model=MatterResponse, status_code=201)
async def create_matter(data: MatterCreate, db: AsyncSession = Depends(get_db)):
    matter = Matter(**data.model_dump(exclude_unset=True))
    db.add(matter)
    await db.flush()
    await db.refresh(matter)
    return _to_response(matter)


@router.patch("/{matter_id}", response_model=MatterResponse)
async def update_matter(matter_id: UUID, data: MatterUpdate, db: AsyncSession = Depends(get_db)):
    matter = await db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(404, "Matter not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(matter, field, value)
    await db.flush()
    await db.refresh(matter)
    return _to_response(matter)


@router.delete("/{matter_id}")
async def delete_matter(matter_id: UUID, db: AsyncSession = Depends(get_db)):
    matter = await db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(404, "Matter not found")
    await db.delete(matter)
    return {"status": "deleted", "id": str(matter_id)}
