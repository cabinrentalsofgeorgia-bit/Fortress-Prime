"""
Guestbook API - Digital guides, extras marketplace, and guest portal
BETTER THAN: RueBaRue (dynamic content, personalization, upsells, AI-enhanced)
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel

from backend.core.database import get_db
from backend.models import GuestbookGuide, Extra

router = APIRouter()


# ============================================================
# Response Models
# ============================================================

class GuideResponse(BaseModel):
    id: UUID
    title: str
    slug: str
    guide_type: str
    category: Optional[str]
    content: str
    icon: Optional[str]
    display_order: int
    is_visible: bool
    view_count: int
    property_id: Optional[UUID]

    class Config:
        from_attributes = True


class ExtraResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    category: Optional[str]
    price: float
    is_available: bool
    image_url: Optional[str]
    display_order: int

    class Config:
        from_attributes = True


class GuideCreate(BaseModel):
    title: str
    guide_type: str
    category: Optional[str] = None
    content: str
    icon: Optional[str] = None
    display_order: int = 0
    is_visible: bool = True
    property_id: Optional[UUID] = None


# ============================================================
# Guide Endpoints
# ============================================================

@router.get("/", response_model=List[GuideResponse])
async def list_guides(
    guide_type: Optional[str] = Query(None),
    property_id: Optional[UUID] = Query(None),
    visible_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """List all guestbook guides with optional filters"""
    query = select(GuestbookGuide)

    if guide_type:
        query = query.where(GuestbookGuide.guide_type == guide_type)
    if property_id:
        query = query.where(
            (GuestbookGuide.property_id == property_id) | (GuestbookGuide.property_id.is_(None))
        )
    if visible_only:
        query = query.where(GuestbookGuide.is_visible == True)

    query = query.order_by(GuestbookGuide.display_order, GuestbookGuide.title)
    result = await db.execute(query)
    guides = result.scalars().all()

    return [GuideResponse.model_validate(g) for g in guides]


# ============================================================
# Extras Marketplace (must be before /{guide_id} to avoid route conflict)
# ============================================================

@router.get("/extras", response_model=List[ExtraResponse])
async def list_extras(
    available_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """List all available extras for the marketplace"""
    query = select(Extra)

    if available_only:
        query = query.where(Extra.is_available == True)

    query = query.order_by(Extra.display_order, Extra.name)
    result = await db.execute(query)
    extras = result.scalars().all()

    return [ExtraResponse.model_validate(e) for e in extras]


# ============================================================
# Individual Guide Endpoints
# ============================================================

@router.get("/{guide_id}", response_model=GuideResponse)
async def get_guide(guide_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific guide"""
    guide = await db.get(GuestbookGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    return GuideResponse.model_validate(guide)


@router.post("/", response_model=GuideResponse, status_code=201)
async def create_guide(data: GuideCreate, db: AsyncSession = Depends(get_db)):
    """Create a new guestbook guide"""
    slug = data.title.lower().replace(" ", "-").replace("'", "")
    guide = GuestbookGuide(
        title=data.title,
        slug=slug,
        guide_type=data.guide_type,
        category=data.category,
        content=data.content,
        icon=data.icon,
        display_order=data.display_order,
        is_visible=data.is_visible,
        property_id=data.property_id,
    )
    db.add(guide)
    await db.flush()
    await db.refresh(guide)
    return GuideResponse.model_validate(guide)


@router.post("/{guide_id}/view")
async def track_guide_view(guide_id: UUID, db: AsyncSession = Depends(get_db)):
    """Track a guide view (for analytics)"""
    await db.execute(
        update(GuestbookGuide)
        .where(GuestbookGuide.id == guide_id)
        .values(view_count=GuestbookGuide.view_count + 1)
    )
    return {"status": "tracked"}
