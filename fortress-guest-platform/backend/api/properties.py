"""Properties API - Property/cabin management."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from arq.connections import ArqRedis
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.models import Property
from backend.schemas.media import PropertyImageResponse

router = APIRouter()


async def _enqueue_property_knowledge_reindex(redis: ArqRedis, property_id: UUID) -> None:
    await redis.enqueue_job(
        "reindex_property_knowledge",
        str(property_id),
        _queue_name=settings.arq_queue_name,
    )


class PropertyResponse(BaseModel):
    """Property response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    property_type: str
    bedrooms: int
    bathrooms: float
    max_guests: int
    wifi_ssid: Optional[str]
    wifi_password: Optional[str]
    access_code_type: Optional[str]
    parking_instructions: Optional[str]
    is_active: bool
    images: list[PropertyImageResponse] = Field(default_factory=list)


def _property_select():
    return select(Property).execution_options(populate_existing=True).options(selectinload(Property.images))


async def _load_property(db: AsyncSession, property_id: UUID) -> Property | None:
    result = await db.execute(_property_select().where(Property.id == property_id))
    return result.scalar_one_or_none()


@router.get("/", response_model=list[PropertyResponse])
async def list_properties(
    is_active: Optional[bool] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List all properties."""

    query = _property_select()
    if is_active is not None:
        query = query.where(Property.is_active == is_active)

    query = query.limit(limit).order_by(Property.name)
    result = await db.execute(query)
    properties = result.scalars().all()
    return [PropertyResponse.model_validate(p) for p in properties]


class PropertyCreate(BaseModel):
    """Property creation request"""
    name: str
    slug: str
    property_type: str = "cabin"
    bedrooms: int = 2
    bathrooms: float = 1.0
    max_guests: int = 6
    wifi_ssid: Optional[str] = None
    wifi_password: Optional[str] = None
    access_code_type: Optional[str] = "keypad"
    parking_instructions: Optional[str] = None


@router.post("/", response_model=PropertyResponse, status_code=201)
async def create_property(
    data: PropertyCreate,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    """Create a new property."""

    prop = Property(
        name=data.name,
        slug=data.slug,
        property_type=data.property_type,
        bedrooms=data.bedrooms,
        bathrooms=data.bathrooms,
        max_guests=data.max_guests,
        wifi_ssid=data.wifi_ssid,
        wifi_password=data.wifi_password,
        access_code_type=data.access_code_type,
        parking_instructions=data.parking_instructions,
    )
    db.add(prop)
    await db.commit()
    await _enqueue_property_knowledge_reindex(arq_redis, prop.id)
    property_record = await _load_property(db, prop.id)
    if property_record is None:
        raise HTTPException(status_code=404, detail="Property not found after create")
    return PropertyResponse.model_validate(property_record)


class PropertyUpdate(BaseModel):
    """Fields that can be patched on a property"""
    name: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    max_guests: Optional[int] = None
    wifi_ssid: Optional[str] = None
    wifi_password: Optional[str] = None
    access_code_type: Optional[str] = None
    access_code_location: Optional[str] = None
    parking_instructions: Optional[str] = None
    is_active: Optional[bool] = None


@router.patch("/{property_id}", response_model=PropertyResponse)
async def update_property(
    property_id: UUID,
    body: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    """Update a property's details."""
    prop = await _load_property(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prop, field, value)

    prop.updated_at = datetime.utcnow()

    await db.commit()
    await _enqueue_property_knowledge_reindex(arq_redis, prop.id)
    property_record = await _load_property(db, prop.id)
    if property_record is None:
        raise HTTPException(status_code=404, detail="Property not found after update")
    return PropertyResponse.model_validate(property_record)


@router.get("/{property_id}", response_model=PropertyResponse)
async def get_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get property by ID."""

    prop = await _load_property(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    return PropertyResponse.model_validate(prop)
