"""
Transactional inventory hold service backed by fortress_prod.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time import utc_now
from backend.models.reservation_hold import ReservationHold
from backend.services.fast_quote_service import (
    acquire_property_booking_lock,
    assert_property_available_for_stay,
    expire_stale_holds,
)

HOLD_TTL_MINUTES = 15


async def create_inventory_hold(
    db: AsyncSession,
    *,
    property_id: UUID,
    check_in: date,
    check_out: date,
    session_id: str,
    guest_id: UUID | None = None,
    num_guests: int = 1,
    amount_total: Decimal | None = None,
    quote_snapshot: dict[str, Any] | None = None,
    special_requests: str | None = None,
) -> ReservationHold:
    """
    Create a database-backed inventory hold or raise 409 on overlap.
    """
    await acquire_property_booking_lock(db, property_id)
    await expire_stale_holds(db)

    try:
        await assert_property_available_for_stay(db, property_id, check_in, check_out)
    except Exception as exc:
        status_code = getattr(exc, "http_status", 409)
        detail = getattr(exc, "message", "Property is not available for these dates")
        raise HTTPException(status_code=status_code, detail=detail) from exc

    hold = ReservationHold(
        property_id=property_id,
        guest_id=guest_id,
        session_id=session_id,
        check_in_date=check_in,
        check_out_date=check_out,
        num_guests=num_guests,
        status="active",
        amount_total=amount_total,
        quote_snapshot=quote_snapshot,
        special_requests=special_requests,
        expires_at=utc_now() + timedelta(minutes=HOLD_TTL_MINUTES),
    )
    db.add(hold)
    await db.flush()
    return hold
