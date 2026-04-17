"""
Vendors API — Contractor / service-provider directory CRUD.

  GET    /                          list vendors (active_only=true by default)
  GET    /{vendor_id}               fetch one vendor
  POST   /                          create vendor
  PATCH  /{vendor_id}               update vendor
  DELETE /{vendor_id}               soft-deactivate (sets active=False)
  GET    /by-trade/{trade}          vendors for a specific trade category
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.vendor import Vendor

logger = structlog.get_logger(service="vendors_api")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
_UTC = timezone.utc

VALID_TRADES = frozenset([
    "hvac", "plumbing", "electrical", "hot_tub", "appliance",
    "landscaping", "cleaning", "painting", "roofing", "carpentry",
    "pest_control", "pool", "general", "other",
])


# ── Schemas ───────────────────────────────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    trade: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=255)
    insurance_expiry: Optional[date] = None
    active: bool = True
    hourly_rate: Optional[float] = Field(None, ge=0)
    regions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("trade")
    @classmethod
    def _validate_trade(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TRADES:
            raise ValueError(f"trade must be one of: {sorted(VALID_TRADES)}")
        return v


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    trade: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=255)
    insurance_expiry: Optional[date] = None
    active: Optional[bool] = None
    hourly_rate: Optional[float] = Field(None, ge=0)
    regions: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("trade")
    @classmethod
    def _validate_trade(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TRADES:
            raise ValueError(f"trade must be one of: {sorted(VALID_TRADES)}")
        return v


def _vendor_to_dict(v: Vendor) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "name": v.name,
        "trade": v.trade,
        "phone": v.phone,
        "email": v.email,
        "insurance_expiry": v.insurance_expiry.isoformat() if v.insurance_expiry else None,
        "active": v.active,
        "hourly_rate": float(v.hourly_rate) if v.hourly_rate is not None else None,
        "regions": v.regions or [],
        "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_vendors(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    q = select(Vendor).order_by(Vendor.trade.asc().nullslast(), Vendor.name)
    if active_only:
        q = q.where(Vendor.active.is_(True))
    result = await db.execute(q)
    vendors = result.scalars().all()
    return {"vendors": [_vendor_to_dict(v) for v in vendors], "total": len(vendors)}


@router.get("/by-trade/{trade}")
async def list_vendors_by_trade(
    trade: str,
    db: AsyncSession = Depends(get_db),
):
    if trade not in VALID_TRADES:
        raise HTTPException(422, f"Invalid trade. Must be one of: {sorted(VALID_TRADES)}")
    result = await db.execute(
        select(Vendor)
        .where(Vendor.active.is_(True))
        .where(Vendor.trade == trade)
        .order_by(Vendor.name)
    )
    vendors = result.scalars().all()
    return {"vendors": [_vendor_to_dict(v) for v in vendors], "total": len(vendors)}


@router.get("/{vendor_id}")
async def get_vendor(vendor_id: str, db: AsyncSession = Depends(get_db)):
    try:
        vid = _uuid.UUID(vendor_id)
    except ValueError:
        raise HTTPException(422, "Invalid vendor_id UUID")
    vendor = await db.get(Vendor, vid)
    if not vendor:
        raise HTTPException(404, f"Vendor {vendor_id} not found")
    return _vendor_to_dict(vendor)


@router.post("", status_code=201)
async def create_vendor(body: VendorCreate, db: AsyncSession = Depends(get_db)):
    vendor = Vendor(
        name=body.name,
        trade=body.trade,
        phone=body.phone,
        email=body.email,
        insurance_expiry=body.insurance_expiry,
        active=body.active,
        hourly_rate=body.hourly_rate,
        regions=body.regions,
        notes=body.notes,
    )
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    logger.info("vendor_created", vendor_id=str(vendor.id), name=vendor.name, trade=vendor.trade)
    return _vendor_to_dict(vendor)


@router.patch("/{vendor_id}")
async def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        vid = _uuid.UUID(vendor_id)
    except ValueError:
        raise HTTPException(422, "Invalid vendor_id UUID")
    vendor = await db.get(Vendor, vid)
    if not vendor:
        raise HTTPException(404, f"Vendor {vendor_id} not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    vendor.updated_at = datetime.now(_UTC)  # type: ignore[assignment]

    await db.commit()
    await db.refresh(vendor)
    logger.info("vendor_updated", vendor_id=vendor_id)
    return _vendor_to_dict(vendor)


@router.delete("/{vendor_id}")
async def deactivate_vendor(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete: sets active=False. FK references remain intact."""
    try:
        vid = _uuid.UUID(vendor_id)
    except ValueError:
        raise HTTPException(422, "Invalid vendor_id UUID")
    vendor = await db.get(Vendor, vid)
    if not vendor:
        raise HTTPException(404, f"Vendor {vendor_id} not found")
    vendor.active = False  # type: ignore[assignment]
    vendor.updated_at = datetime.now(_UTC)  # type: ignore[assignment]
    await db.commit()
    logger.info("vendor_deactivated", vendor_id=vendor_id)
    return {"deactivated": True, "vendor_id": vendor_id}
