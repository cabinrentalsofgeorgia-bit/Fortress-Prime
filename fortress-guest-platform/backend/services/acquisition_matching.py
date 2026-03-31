"""
Shared matching and signal helpers for CROG acquisition intelligence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.acquisition import (
    AcquisitionOwner,
    AcquisitionParcel,
    AcquisitionProperty,
    AcquisitionSTRSignal,
    SignalSource,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_parcel_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def normalize_name(value: str | None) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).split())


def normalize_address(value: str | None) -> str:
    normalized = str(value or "").upper()
    replacements = {
        " ROAD ": " RD ",
        " STREET ": " ST ",
        " AVENUE ": " AVE ",
        " DRIVE ": " DR ",
        " HIGHWAY ": " HWY ",
        " TRAIL ": " TRL ",
        " LANE ": " LN ",
        " COURT ": " CT ",
        " PLACE ": " PL ",
        " BOULEVARD ": " BLVD ",
        " MOUNTAIN ": " MTN ",
        " TRACE ": " TRCE ",
    }
    normalized = f" {re.sub(r'[^A-Z0-9]+', ' ', normalized)} "
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


async def resolve_parcel_by_id(db: AsyncSession, parcel_id: str | None) -> AcquisitionParcel | None:
    normalized_target = normalize_parcel_id(parcel_id)
    if not normalized_target:
        return None
    parcels = (await db.execute(select(AcquisitionParcel))).scalars().all()
    for parcel in parcels:
        if normalize_parcel_id(parcel.parcel_id) == normalized_target:
            return parcel
    return None


async def resolve_owner(
    db: AsyncSession,
    *,
    legal_name: str | None,
    mailing_address: str | None,
) -> AcquisitionOwner | None:
    normalized_name = normalize_name(legal_name)
    normalized_address = normalize_address(mailing_address)
    if not normalized_name and not normalized_address:
        return None
    owners = (await db.execute(select(AcquisitionOwner))).scalars().all()
    for owner in owners:
        if normalized_name and normalize_name(owner.legal_name) != normalized_name:
            continue
        if normalized_address and normalize_address(owner.tax_mailing_address) != normalized_address:
            continue
        return owner
    return None


async def ensure_property_for_parcel(
    db: AsyncSession,
    *,
    parcel: AcquisitionParcel,
    owner: AcquisitionOwner | None = None,
) -> AcquisitionProperty:
    stmt = select(AcquisitionProperty).where(AcquisitionProperty.parcel_id == parcel.id).limit(1)
    prop = (await db.execute(stmt)).scalar_one_or_none()
    if prop is None:
        prop = AcquisitionProperty(
            parcel_id=parcel.id,
            owner_id=owner.id if owner is not None else None,
        )
        db.add(prop)
        await db.flush()
        return prop
    if owner is not None and prop.owner_id is None:
        prop.owner_id = owner.id
    return prop


async def resolve_property_by_address(
    db: AsyncSession,
    *,
    address: str | None,
) -> AcquisitionProperty | None:
    normalized_target = normalize_address(address)
    if not normalized_target:
        return None
    stmt = (
        select(AcquisitionProperty)
        .options(
            selectinload(AcquisitionProperty.owner),
            selectinload(AcquisitionProperty.intel_events),
        )
        .join(AcquisitionParcel)
    )
    properties = (await db.execute(stmt)).scalars().all()
    for prop in properties:
        for event in prop.intel_events or []:
            payload = event.raw_source_data or {}
            source_address = payload.get("property_address")
            if normalize_address(str(source_address or "")) == normalized_target:
                return prop
        if prop.owner and normalize_address(prop.owner.tax_mailing_address) == normalized_target:
            return prop
    return None


async def resolve_property_by_coordinates(
    db: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_meters: int = 75,
) -> tuple[AcquisitionProperty | None, bool]:
    contains_stmt = text(
        """
        SELECT p.id
        FROM crog_acquisition.properties AS p
        JOIN crog_acquisition.parcels AS parcels ON parcels.id = p.parcel_id
        WHERE parcels.geom IS NOT NULL
          AND ST_Contains(
                parcels.geom,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
              )
        LIMIT 1
        """
    )
    row = (await db.execute(contains_stmt, {"longitude": longitude, "latitude": latitude})).first()
    if row:
        return await db.get(AcquisitionProperty, row[0]), True

    nearby_stmt = text(
        """
        SELECT p.id
        FROM crog_acquisition.properties AS p
        JOIN crog_acquisition.parcels AS parcels ON parcels.id = p.parcel_id
        WHERE parcels.geom IS NOT NULL
          AND ST_DWithin(
                parcels.geom::geography,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                :radius_meters
              )
        ORDER BY ST_Distance(
            parcels.geom::geography,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
        ) ASC
        LIMIT 1
        """
    )
    row = (
        await db.execute(
            nearby_stmt,
            {"longitude": longitude, "latitude": latitude, "radius_meters": radius_meters},
        )
    ).first()
    if row:
        return await db.get(AcquisitionProperty, row[0]), False
    return None, False


async def create_str_signal(
    db: AsyncSession,
    *,
    property_id: UUID,
    signal_source: SignalSource,
    confidence_score: float | Decimal,
    raw_payload: dict[str, Any],
    detected_at: datetime | None = None,
) -> AcquisitionSTRSignal:
    signal = AcquisitionSTRSignal(
        property_id=property_id,
        signal_source=signal_source,
        confidence_score=Decimal(str(confidence_score)),
        raw_payload=json_safe(raw_payload),
        detected_at=detected_at or utcnow(),
    )
    db.add(signal)
    await db.flush()
    return signal


async def recent_str_signals(
    db: AsyncSession,
    *,
    property_id: UUID,
    limit: int = 5,
) -> list[AcquisitionSTRSignal]:
    stmt = (
        select(AcquisitionSTRSignal)
        .where(AcquisitionSTRSignal.property_id == property_id)
        .order_by(AcquisitionSTRSignal.detected_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
