"""
Leads API — CRUD and listing for the Agentic Lead Engine inbox.

Endpoints:
  GET  /api/leads-inbox/              — List all leads (paginated, filterable)
  GET  /api/leads-inbox/{lead_id}     — Single lead detail with quotes
  PATCH /api/leads-inbox/{lead_id}    — Update lead status/score
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.models.lead import Lead
from backend.models.quote import Quote

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────


class QuoteSnapshot(BaseModel):
    quote_id: UUID
    status: str
    payment_method: Optional[str] = None
    grand_total: str = "0.00"
    created_at: Optional[datetime] = None


class LeadSummary(BaseModel):
    id: UUID
    guest_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    guest_message: Optional[str] = None
    status: str = "new"
    ai_score: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    quote_count: int = 0
    latest_quote: Optional[QuoteSnapshot] = None


class LeadListResponse(BaseModel):
    data: List[LeadSummary]
    total: int
    page: int
    per_page: int


class LeadUpdateRequest(BaseModel):
    status: Optional[str] = None
    ai_score: Optional[int] = None
    guest_name: Optional[str] = None
    guest_message: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_quote_snapshot(lead: Lead) -> Optional[QuoteSnapshot]:
    """Pick the most recent quote and compute its grand_total from QuoteOptions."""
    if not lead.quotes:
        return None
    latest = max(lead.quotes, key=lambda q: q.created_at or datetime.min)
    grand_total = sum(
        (opt.total_price or Decimal("0")) for opt in (latest.options or [])
    )
    return QuoteSnapshot(
        quote_id=latest.id,
        status=latest.status or "draft",
        payment_method=latest.payment_method,
        grand_total=str(grand_total),
        created_at=latest.created_at,
    )


def _lead_to_summary(lead: Lead) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        guest_name=lead.guest_name,
        email=lead.email,
        phone=lead.phone,
        guest_message=lead.guest_message,
        status=lead.status or "new",
        ai_score=lead.ai_score,
        source=lead.source,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        quote_count=len(lead.quotes) if lead.quotes else 0,
        latest_quote=_build_quote_snapshot(lead),
    )


_LEAD_EAGER = selectinload(Lead.quotes).selectinload(Quote.options)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("created_at", pattern="^(created_at|guest_name|status|ai_score)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    """List all leads with pagination, filtering, and search."""
    query = select(Lead)
    count_query = select(func.count(Lead.id))

    if status:
        query = query.where(Lead.status == status)
        count_query = count_query.where(Lead.status == status)

    if search:
        pattern = f"%{search}%"
        search_filter = (
            Lead.guest_name.ilike(pattern)
            | Lead.email.ilike(pattern)
            | Lead.phone.ilike(pattern)
            | Lead.guest_message.ilike(pattern)
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    sort_col = getattr(Lead, sort_by)
    if order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    query = query.options(_LEAD_EAGER)

    result = await db.execute(query)
    leads = result.scalars().all()

    return LeadListResponse(
        data=[_lead_to_summary(lead) for lead in leads],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{lead_id}", response_model=LeadSummary)
async def get_lead(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a single lead by ID."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(_LEAD_EAGER)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return _lead_to_summary(lead)


@router.patch("/{lead_id}", response_model=LeadSummary)
async def update_lead(
    lead_id: UUID,
    body: LeadUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update lead status, score, or details."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(_LEAD_EAGER)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    if body.status is not None:
        lead.status = body.status
    if body.ai_score is not None:
        lead.ai_score = body.ai_score
    if body.guest_name is not None:
        lead.guest_name = body.guest_name
    if body.guest_message is not None:
        lead.guest_message = body.guest_message

    lead.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(lead)

    return _lead_to_summary(lead)
