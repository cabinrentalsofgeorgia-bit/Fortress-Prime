"""
Fast quote — local Postgres ledger only (no live Streamline on request path).

Availability: reservations (occupying statuses), blocked_days, active reservation_holds.
Pricing: properties.rate_card via calculate_property_quote; requires populated rate_card rates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.blocked_day import BlockedDay
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.models.reservation_hold import ReservationHold
from backend.core.time import utc_now
from backend.services.quote_builder import QuoteBuilderError, build_local_ledger_quote

logger = structlog.get_logger()

OCCUPYING_RESERVATION_STATUSES = ("pending", "confirmed", "checked_in", "pending_payment")


@dataclass(frozen=True)
class FastQuoteBreakdown:
    rent: Decimal
    cleaning: Decimal
    taxes: Decimal
    total: Decimal


class FastQuoteError(Exception):
    """Domain error for fast quote (mapped to HTTP in the route)."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


async def acquire_property_booking_lock(db: AsyncSession, property_id: UUID) -> None:
    """Serialize checkout mutations per property for the current transaction."""
    lock_key = _property_lock_key(property_id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _property_lock_key(property_id: UUID) -> int:
    """Derive a stable signed 64-bit advisory lock key from the property UUID."""
    unsigned_64 = property_id.int & ((1 << 64) - 1)
    return unsigned_64 if unsigned_64 < (1 << 63) else unsigned_64 - (1 << 64)


def _missing_runtime_table(exc: ProgrammingError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "does not exist" in message or "undefinedtable" in message


async def expire_stale_holds(db: AsyncSession) -> int:
    """Mark active holds past expires_at as expired. Returns rows updated."""
    now = utc_now()
    try:
        result = await db.execute(
            text("""
                UPDATE reservation_holds
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'active' AND expires_at < :now
            """),
            {"now": now},
        )
        return result.rowcount or 0
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("fast_quote_reservation_holds_table_missing")
        await db.rollback()
        return 0


async def has_blocked_day_conflict(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
) -> bool:
    stmt = (
        select(func.count())
        .select_from(BlockedDay)
        .where(
            and_(
                BlockedDay.property_id == property_id,
                BlockedDay.start_date < check_out,
                BlockedDay.end_date > check_in,
            )
        )
    )
    try:
        n = (await db.execute(stmt)).scalar_one()
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("fast_quote_blocked_days_table_missing")
        await db.rollback()
        return False
    return int(n) > 0


async def has_reservation_conflict(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    exclude_reservation_id: UUID | None = None,
) -> bool:
    conds = [
        Reservation.property_id == property_id,
        Reservation.status.in_(OCCUPYING_RESERVATION_STATUSES),
        Reservation.check_in_date < check_out,
        Reservation.check_out_date > check_in,
    ]
    stmt = select(func.count()).select_from(Reservation).where(and_(*conds))
    if exclude_reservation_id is not None:
        stmt = stmt.where(Reservation.id != exclude_reservation_id)
    try:
        n = (await db.execute(stmt)).scalar_one()
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("fast_quote_reservations_table_missing")
        await db.rollback()
        return False
    return int(n) > 0


async def has_active_hold_conflict(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    exclude_hold_id: UUID | None = None,
) -> bool:
    now = utc_now()
    conds = [
        ReservationHold.property_id == property_id,
        ReservationHold.status == "active",
        ReservationHold.expires_at > now,
        ReservationHold.check_in_date < check_out,
        ReservationHold.check_out_date > check_in,
    ]
    stmt = select(func.count()).select_from(ReservationHold).where(and_(*conds))
    if exclude_hold_id is not None:
        stmt = stmt.where(ReservationHold.id != exclude_hold_id)
    try:
        n = (await db.execute(stmt)).scalar_one()
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("fast_quote_reservation_holds_table_missing")
        await db.rollback()
        return False
    return int(n) > 0


async def assert_property_available_for_stay(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    *,
    exclude_reservation_id: UUID | None = None,
    exclude_hold_id: UUID | None = None,
) -> None:
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise FastQuoteError("property_not_found", "Property not found", 404)

    if await has_blocked_day_conflict(db, property_id, check_in, check_out):
        raise FastQuoteError("dates_blocked", "Property is not available for these dates", 409)

    if await has_reservation_conflict(
        db, property_id, check_in, check_out, exclude_reservation_id=exclude_reservation_id
    ):
        raise FastQuoteError("dates_booked", "Property is not available for these dates", 409)

    if await has_active_hold_conflict(
        db, property_id, check_in, check_out, exclude_hold_id=exclude_hold_id
    ):
        raise FastQuoteError("dates_held", "Property is temporarily held for checkout", 409)


async def compute_fast_quote_breakdown(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    guests: int,
) -> FastQuoteBreakdown:
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise FastQuoteError("property_not_found", "Property not found", 404)

    if guests > prop.max_guests:
        raise FastQuoteError("too_many_guests", "Guest count exceeds property maximum", 422)

    try:
        quote = await build_local_ledger_quote(property_id, check_in, check_out, db)
    except QuoteBuilderError as exc:
        raise FastQuoteError(
            "pricing_ledger_incomplete",
            str(exc),
            503,
        ) from exc

    return FastQuoteBreakdown(
        rent=quote.rent,
        cleaning=quote.cleaning,
        taxes=quote.taxes,
        total=quote.total,
    )


async def calculate_locked_fast_quote_breakdown(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    guests: int,
) -> FastQuoteBreakdown:
    """
    Quote a stay inside the same transaction/lock envelope used by checkout holds.

    Order matters here:
    1. acquire the property-scoped advisory lock
    2. expire stale holds
    3. validate availability against blocked days, reservations, and active holds
    4. compute the local-ledger quote
    """
    await acquire_property_booking_lock(db, property_id)
    await expire_stale_holds(db)
    await assert_property_available_for_stay(db, property_id, check_in, check_out)
    return await compute_fast_quote_breakdown(db, property_id, check_in, check_out, guests)


def breakdown_to_response_dict(b: FastQuoteBreakdown) -> dict[str, float]:
    def _f(d: Decimal) -> float:
        return float(d.quantize(Decimal("0.01")))

    return {
        "rent": _f(b.rent),
        "cleaning": _f(b.cleaning),
        "taxes": _f(b.taxes),
        "total": _f(b.total),
    }


async def build_quote_snapshot(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    guests: int,
) -> dict[str, Any]:
    """Persistable pricing snapshot for a hold / reservation."""
    b = await compute_fast_quote_breakdown(db, property_id, check_in, check_out, guests)
    prop = await db.get(Property, property_id)
    return {
        "property_id": str(property_id),
        "property_name": prop.name if prop else "",
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "guests": guests,
        "rent": str(b.rent),
        "cleaning": str(b.cleaning),
        "taxes": str(b.taxes),
        "total": str(b.total),
    }
