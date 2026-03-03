"""
Attorneys API — CRUD for managing attorneys and law firms.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, desc, func
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.models.attorney import Attorney

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class AttorneyCreate(BaseModel):
    first_name: str
    last_name: str
    firm_name: Optional[str] = None
    specialty: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    bar_number: Optional[str] = None
    bar_state: Optional[str] = None
    hourly_rate: Optional[Decimal] = None
    retainer_amount: Optional[Decimal] = None
    retainer_status: str = "none"
    engagement_date: Optional[date] = None
    status: str = "active"
    rating: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class AttorneyUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    firm_name: Optional[str] = None
    specialty: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    bar_number: Optional[str] = None
    bar_state: Optional[str] = None
    hourly_rate: Optional[Decimal] = None
    retainer_amount: Optional[Decimal] = None
    retainer_status: Optional[str] = None
    engagement_date: Optional[date] = None
    status: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class AttorneyResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    full_name: str = ""
    firm_name: Optional[str] = None
    specialty: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    bar_number: Optional[str] = None
    bar_state: Optional[str] = None
    hourly_rate: Optional[Decimal] = None
    retainer_amount: Optional[Decimal] = None
    retainer_status: Optional[str] = "none"
    engagement_date: Optional[date] = None
    status: Optional[str] = "active"
    rating: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    matter_count: int = 0
    meeting_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_response(a: Attorney) -> AttorneyResponse:
    return AttorneyResponse(
        id=a.id,
        first_name=a.first_name,
        last_name=a.last_name,
        full_name=f"{a.first_name} {a.last_name}",
        firm_name=a.firm_name,
        specialty=a.specialty,
        email=a.email,
        phone=a.phone,
        address=a.address,
        website=a.website,
        bar_number=a.bar_number,
        bar_state=a.bar_state,
        hourly_rate=a.hourly_rate,
        retainer_amount=a.retainer_amount,
        retainer_status=a.retainer_status,
        engagement_date=a.engagement_date,
        status=a.status,
        rating=a.rating,
        notes=a.notes,
        tags=a.tags,
        matter_count=len(a.matters) if a.matters else 0,
        meeting_count=len(a.meetings) if a.meetings else 0,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AttorneyResponse])
async def list_attorneys(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Attorney).order_by(desc(Attorney.updated_at))
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            Attorney.first_name.ilike(term),
            Attorney.last_name.ilike(term),
            Attorney.firm_name.ilike(term),
        ))
    if status:
        query = query.where(Attorney.status == status)
    if specialty:
        query = query.where(Attorney.specialty == specialty)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(a) for a in result.scalars().all()]


@router.get("/count")
async def count_attorneys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(Attorney.id)))
    return {"count": result.scalar_one()}


@router.get("/{attorney_id}", response_model=AttorneyResponse)
async def get_attorney(attorney_id: UUID, db: AsyncSession = Depends(get_db)):
    a = await db.get(Attorney, attorney_id)
    if not a:
        raise HTTPException(404, "Attorney not found")
    return _to_response(a)


@router.post("/", response_model=AttorneyResponse, status_code=201)
async def create_attorney(data: AttorneyCreate, db: AsyncSession = Depends(get_db)):
    attorney = Attorney(**data.model_dump(exclude_unset=True))
    db.add(attorney)
    await db.flush()
    await db.refresh(attorney)
    return _to_response(attorney)


@router.patch("/{attorney_id}", response_model=AttorneyResponse)
async def update_attorney(attorney_id: UUID, data: AttorneyUpdate, db: AsyncSession = Depends(get_db)):
    attorney = await db.get(Attorney, attorney_id)
    if not attorney:
        raise HTTPException(404, "Attorney not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(attorney, field, value)
    await db.flush()
    await db.refresh(attorney)
    return _to_response(attorney)


@router.delete("/{attorney_id}")
async def delete_attorney(attorney_id: UUID, db: AsyncSession = Depends(get_db)):
    attorney = await db.get(Attorney, attorney_id)
    if not attorney:
        raise HTTPException(404, "Attorney not found")
    await db.delete(attorney)
    return {"status": "deleted", "id": str(attorney_id)}
