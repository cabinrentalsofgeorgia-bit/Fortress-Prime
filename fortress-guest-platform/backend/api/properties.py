"""
Properties API - Property/cabin management
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from backend.core.database import get_db
from backend.models import Property

router = APIRouter()


class PropertyResponse(BaseModel):
    """Property response"""
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
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[PropertyResponse])
async def list_properties(
    is_active: Optional[bool] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """List all properties"""
    query = select(Property)
    
    if is_active is not None:
        query = query.where(Property.is_active == is_active)
    
    query = query.limit(limit).order_by(Property.name)
    
    result = await db.execute(query)
    properties = result.scalars().all()
    
    return [PropertyResponse.from_orm(p) for p in properties]


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
):
    """Create a new property"""
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
    await db.flush()
    await db.refresh(prop)
    return PropertyResponse.model_validate(prop)


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
):
    """Update a property's details."""
    prop = await db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prop, field, value)

    from datetime import datetime
    prop.updated_at = datetime.utcnow()

    await db.flush()
    await db.refresh(prop)
    return PropertyResponse.model_validate(prop)


@router.get("/{property_id}", response_model=PropertyResponse)
async def get_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get property by ID"""
    prop = await db.get(Property, property_id)
    
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    return PropertyResponse.model_validate(prop)
