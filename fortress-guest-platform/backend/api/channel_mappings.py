"""
Channel Mappings API — CRUD for property ↔ OTA external listing ID mappings.

Endpoints:
  GET  /channel-mappings                     — List all mappings (filterable by channel/property)
  GET  /channel-mappings/{property_id}       — Get all mappings for a property
  POST /channel-mappings                     — Create or upsert a mapping
  PATCH /channel-mappings/{mapping_id}       — Update sync_status or external_listing_id
  DELETE /channel-mappings/{mapping_id}      — Delete a mapping
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.channel_mapping import ChannelMapping

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])

VALID_CHANNELS = frozenset(["channex", "airbnb", "vrbo", "booking_com", "ical", "direct"])
VALID_SYNC_STATUSES = frozenset(["active", "paused", "error", "pending"])


class ChannelMappingOut(BaseModel):
    id: UUID
    property_id: UUID
    channel: str
    external_listing_id: str
    sync_status: str
    last_synced_at: Optional[datetime]
    sync_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChannelMappingCreate(BaseModel):
    property_id: UUID
    channel: str
    external_listing_id: str
    sync_status: str = "active"


class ChannelMappingUpdate(BaseModel):
    external_listing_id: Optional[str] = None
    sync_status: Optional[str] = None
    sync_error: Optional[str] = None


@router.get("", response_model=list[ChannelMappingOut])
async def list_channel_mappings(
    channel: Optional[str] = None,
    property_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> list[ChannelMappingOut]:
    """List all channel mappings, optionally filtered by channel or property."""
    q = select(ChannelMapping).order_by(ChannelMapping.created_at.desc())
    if channel:
        q = q.where(ChannelMapping.channel == channel)
    if property_id:
        q = q.where(ChannelMapping.property_id == property_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{property_id}", response_model=list[ChannelMappingOut])
async def get_property_channel_mappings(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ChannelMappingOut]:
    """Get all channel mappings for a specific property."""
    result = await db.execute(
        select(ChannelMapping)
        .where(ChannelMapping.property_id == property_id)
        .order_by(ChannelMapping.channel)
    )
    return result.scalars().all()


@router.post("", response_model=ChannelMappingOut, status_code=201)
async def create_channel_mapping(
    body: ChannelMappingCreate,
    db: AsyncSession = Depends(get_db),
) -> ChannelMappingOut:
    """Create or upsert a channel mapping (idempotent on property_id + channel)."""
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(422, f"channel must be one of: {sorted(VALID_CHANNELS)}")
    if body.sync_status not in VALID_SYNC_STATUSES:
        raise HTTPException(422, f"sync_status must be one of: {sorted(VALID_SYNC_STATUSES)}")

    # Upsert: update if exists
    existing = (await db.execute(
        select(ChannelMapping)
        .where(ChannelMapping.property_id == body.property_id)
        .where(ChannelMapping.channel == body.channel)
    )).scalar_one_or_none()

    if existing:
        existing.external_listing_id = body.external_listing_id
        existing.sync_status = body.sync_status
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    mapping = ChannelMapping(
        property_id=body.property_id,
        channel=body.channel,
        external_listing_id=body.external_listing_id,
        sync_status=body.sync_status,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    return mapping


@router.patch("/{mapping_id}", response_model=ChannelMappingOut)
async def update_channel_mapping(
    mapping_id: UUID,
    body: ChannelMappingUpdate,
    db: AsyncSession = Depends(get_db),
) -> ChannelMappingOut:
    """Update a channel mapping's status, listing ID, or error text."""
    mapping = await db.get(ChannelMapping, mapping_id)
    if not mapping:
        raise HTTPException(404, f"Channel mapping {mapping_id} not found")

    if body.external_listing_id is not None:
        mapping.external_listing_id = body.external_listing_id
    if body.sync_status is not None:
        if body.sync_status not in VALID_SYNC_STATUSES:
            raise HTTPException(422, f"sync_status must be one of: {sorted(VALID_SYNC_STATUSES)}")
        mapping.sync_status = body.sync_status
    if body.sync_error is not None:
        mapping.sync_error = body.sync_error or None

    mapping.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=204)
async def delete_channel_mapping(
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a channel mapping."""
    mapping = await db.get(ChannelMapping, mapping_id)
    if not mapping:
        raise HTTPException(404, f"Channel mapping {mapping_id} not found")
    await db.delete(mapping)
    await db.commit()
