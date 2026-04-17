"""
Cleaners API — Cleaner directory CRUD.

Provides endpoints for managing cleaning contractors:
  GET    /                   list active cleaners
  GET    /{cleaner_id}       fetch one cleaner
  POST   /                   create cleaner
  PATCH  /{cleaner_id}       update cleaner
  DELETE /{cleaner_id}       soft-deactivate (sets active=False)
  GET    /by-property/{pid}  cleaners assigned to a specific property
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.cleaner import Cleaner

logger = structlog.get_logger(service="cleaners_api")

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])

_UTC = timezone.utc


# ── Schemas ───────────────────────────────────────────────────────────────────


class CleanerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=255)
    active: bool = True
    per_clean_rate: Optional[float] = Field(None, ge=0)
    hourly_rate: Optional[float] = Field(None, ge=0)
    property_ids: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("property_ids", mode="before")
    @classmethod
    def _validate_uuids(cls, v: Any) -> List[str]:
        result = []
        for item in v or []:
            try:
                result.append(str(_uuid.UUID(str(item))))
            except ValueError:
                raise ValueError(f"Invalid UUID in property_ids: {item!r}")
        return result


class CleanerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=255)
    active: Optional[bool] = None
    per_clean_rate: Optional[float] = Field(None, ge=0)
    hourly_rate: Optional[float] = Field(None, ge=0)
    property_ids: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("property_ids", mode="before")
    @classmethod
    def _validate_uuids(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        result = []
        for item in v:
            try:
                result.append(str(_uuid.UUID(str(item))))
            except ValueError:
                raise ValueError(f"Invalid UUID in property_ids: {item!r}")
        return result


def _cleaner_to_dict(c: Cleaner) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "active": c.active,
        "per_clean_rate": float(c.per_clean_rate) if c.per_clean_rate is not None else None,
        "hourly_rate": float(c.hourly_rate) if c.hourly_rate is not None else None,
        "property_ids": c.property_ids or [],
        "regions": c.regions or [],
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_cleaners(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List cleaners, optionally filtered to active-only (default: True)."""
    q = select(Cleaner).order_by(Cleaner.name)
    if active_only:
        q = q.where(Cleaner.active.is_(True))
    result = await db.execute(q)
    cleaners = result.scalars().all()
    return {"cleaners": [_cleaner_to_dict(c) for c in cleaners], "total": len(cleaners)}


@router.get("/by-property/{property_id}")
async def list_cleaners_for_property(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return active cleaners assigned to a specific property UUID."""
    try:
        pid = str(_uuid.UUID(property_id))
    except ValueError:
        raise HTTPException(422, "Invalid property_id UUID")

    result = await db.execute(
        select(Cleaner)
        .where(Cleaner.active.is_(True))
        .where(Cleaner.property_ids.contains([pid]))  # type: ignore[arg-type]
        .order_by(Cleaner.name)
    )
    cleaners = result.scalars().all()
    return {"cleaners": [_cleaner_to_dict(c) for c in cleaners], "total": len(cleaners)}


@router.get("/{cleaner_id}")
async def get_cleaner(cleaner_id: str, db: AsyncSession = Depends(get_db)):
    try:
        cid = _uuid.UUID(cleaner_id)
    except ValueError:
        raise HTTPException(422, "Invalid cleaner_id UUID")

    cleaner = await db.get(Cleaner, cid)
    if not cleaner:
        raise HTTPException(404, f"Cleaner {cleaner_id} not found")
    return _cleaner_to_dict(cleaner)


@router.post("", status_code=201)
async def create_cleaner(body: CleanerCreate, db: AsyncSession = Depends(get_db)):
    cleaner = Cleaner(
        name=body.name,
        phone=body.phone,
        email=body.email,
        active=body.active,
        per_clean_rate=body.per_clean_rate,
        hourly_rate=body.hourly_rate,
        property_ids=body.property_ids,
        regions=body.regions,
        notes=body.notes,
    )
    db.add(cleaner)
    await db.commit()
    await db.refresh(cleaner)
    logger.info("cleaner_created", cleaner_id=str(cleaner.id), name=cleaner.name)
    return _cleaner_to_dict(cleaner)


@router.patch("/{cleaner_id}")
async def update_cleaner(
    cleaner_id: str,
    body: CleanerUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        cid = _uuid.UUID(cleaner_id)
    except ValueError:
        raise HTTPException(422, "Invalid cleaner_id UUID")

    cleaner = await db.get(Cleaner, cid)
    if not cleaner:
        raise HTTPException(404, f"Cleaner {cleaner_id} not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(cleaner, field, value)
    cleaner.updated_at = datetime.now(_UTC)  # type: ignore[assignment]

    await db.commit()
    await db.refresh(cleaner)
    logger.info("cleaner_updated", cleaner_id=cleaner_id, fields=list(updates.keys()))
    return _cleaner_to_dict(cleaner)


@router.delete("/{cleaner_id}", status_code=200)
async def deactivate_cleaner(cleaner_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete: sets active=False. Does not remove DB row or FK references."""
    try:
        cid = _uuid.UUID(cleaner_id)
    except ValueError:
        raise HTTPException(422, "Invalid cleaner_id UUID")

    cleaner = await db.get(Cleaner, cid)
    if not cleaner:
        raise HTTPException(404, f"Cleaner {cleaner_id} not found")

    cleaner.active = False  # type: ignore[assignment]
    cleaner.updated_at = datetime.now(_UTC)  # type: ignore[assignment]
    await db.commit()
    logger.info("cleaner_deactivated", cleaner_id=cleaner_id)
    return {"deactivated": True, "cleaner_id": cleaner_id}
