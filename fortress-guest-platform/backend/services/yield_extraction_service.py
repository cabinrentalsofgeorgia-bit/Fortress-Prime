"""
Read-only financial context extraction for the sovereign booking ledger.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time import utc_now
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.models.reservation_hold import ReservationHold

CONVERTED_RESERVATION_STATUSES = ("confirmed", "checked_in", "checked_out", "no_show")
CALENDAR_BLOCKING_RESERVATION_STATUSES = ("pending", "confirmed", "checked_in", "pending_payment")


class BookingVelocityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(ge=1)
    converted_reservations: int = Field(ge=0)
    converted_revenue: Decimal = Field(default=Decimal("0.00"))
    average_booking_value: Decimal = Field(default=Decimal("0.00"))


class AbandonmentRateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(ge=1)
    expired_holds: int = Field(ge=0)
    converted_holds: int = Field(ge=0)
    abandonment_rate: float = Field(ge=0.0, le=1.0)


class OccupancyGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    nights: int = Field(ge=1)


class FinancialExtractionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    property_name: str
    as_of_date: date
    days_back: int = Field(ge=1)
    window_days: int = Field(ge=1)
    booking_velocity: BookingVelocityMetrics
    abandonment: AbandonmentRateMetrics
    occupancy_gaps: list[OccupancyGap]


def _to_money(value: Decimal | int | float | None) -> Decimal:
    decimal_value = Decimal(str(value or 0))
    return decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def get_booking_velocity(
    db: AsyncSession,
    days_back: int = 7,
) -> BookingVelocityMetrics:
    """
    Return converted reservation count and revenue for the recent booking window.

    This query is read-only and only scans reservation facts already persisted in
    the sovereign ledger.
    """
    cutoff = utc_now() - timedelta(days=days_back)
    stmt = (
        select(
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.total_amount), 0),
        )
        .where(Reservation.created_at >= cutoff)
        .where(Reservation.status.in_(CONVERTED_RESERVATION_STATUSES))
    )
    row = (await db.execute(stmt)).one()
    converted_reservations = int(row[0] or 0)
    converted_revenue = _to_money(row[1])
    average_booking_value = (
        _to_money(converted_revenue / converted_reservations)
        if converted_reservations > 0
        else Decimal("0.00")
    )
    return BookingVelocityMetrics(
        days_back=days_back,
        converted_reservations=converted_reservations,
        converted_revenue=converted_revenue,
        average_booking_value=average_booking_value,
    )


async def get_abandonment_rate(
    db: AsyncSession,
    days_back: int = 7,
) -> AbandonmentRateMetrics:
    """
    Calculate expired hold ratio versus successful conversions over the same window.
    """
    cutoff = utc_now() - timedelta(days=days_back)
    stmt = (
        select(ReservationHold.status, func.count(ReservationHold.id))
        .where(ReservationHold.created_at >= cutoff)
        .where(ReservationHold.status.in_(("expired", "converted")))
        .group_by(ReservationHold.status)
    )
    rows = (await db.execute(stmt)).all()
    counts = {str(status): int(count or 0) for status, count in rows}
    expired_holds = counts.get("expired", 0)
    converted_holds = counts.get("converted", 0)
    total_terminal_holds = expired_holds + converted_holds
    abandonment_rate = (
        expired_holds / total_terminal_holds if total_terminal_holds > 0 else 0.0
    )
    return AbandonmentRateMetrics(
        days_back=days_back,
        expired_holds=expired_holds,
        converted_holds=converted_holds,
        abandonment_rate=round(abandonment_rate, 4),
    )


async def get_occupancy_gaps(
    db: AsyncSession,
    property_id: UUID,
    window_days: int = 30,
) -> list[OccupancyGap]:
    """
    Identify open stay windows for the target property over the next horizon.

    Reservations in occupying statuses and still-active checkout holds are both
    treated as blocking intervals for this read-only analysis pass.
    """
    window_start = utc_now().date()
    window_end = window_start + timedelta(days=window_days)
    now = utc_now()

    reservation_stmt = (
        select(Reservation.check_in_date, Reservation.check_out_date)
        .where(Reservation.property_id == property_id)
        .where(Reservation.status.in_(CALENDAR_BLOCKING_RESERVATION_STATUSES))
        .where(Reservation.check_in_date < window_end)
        .where(Reservation.check_out_date > window_start)
    )
    hold_stmt = (
        select(ReservationHold.check_in_date, ReservationHold.check_out_date)
        .where(ReservationHold.property_id == property_id)
        .where(ReservationHold.status == "active")
        .where(ReservationHold.expires_at > now)
        .where(ReservationHold.check_in_date < window_end)
        .where(ReservationHold.check_out_date > window_start)
    )

    reservation_rows = (await db.execute(reservation_stmt)).all()
    hold_rows = (await db.execute(hold_stmt)).all()

    intervals: list[tuple[date, date]] = []
    for check_in_date, check_out_date in [*reservation_rows, *hold_rows]:
        start_date = max(check_in_date, window_start)
        end_date = min(check_out_date, window_end)
        if start_date < end_date:
            intervals.append((start_date, end_date))

    intervals.sort(key=lambda item: (item[0], item[1]))

    merged: list[tuple[date, date]] = []
    for start_date, end_date in intervals:
        if not merged or start_date > merged[-1][1]:
            merged.append((start_date, end_date))
            continue
        previous_start, previous_end = merged[-1]
        if end_date > previous_end:
            merged[-1] = (previous_start, end_date)

    gaps: list[OccupancyGap] = []
    cursor = window_start
    for start_date, end_date in merged:
        if cursor < start_date:
            nights = (start_date - cursor).days
            if nights > 0:
                gaps.append(
                    OccupancyGap(
                        start_date=cursor,
                        end_date=start_date,
                        nights=nights,
                    )
                )
        if end_date > cursor:
            cursor = end_date

    if cursor < window_end:
        trailing_nights = (window_end - cursor).days
        if trailing_nights > 0:
            gaps.append(
                OccupancyGap(
                    start_date=cursor,
                    end_date=window_end,
                    nights=trailing_nights,
                )
            )

    return gaps


async def extract_financial_context(
    db: AsyncSession,
    property_id: UUID,
    *,
    days_back: int = 7,
    window_days: int = 30,
) -> FinancialExtractionContext:
    """
    Build the full read-only JSON context consumed by the yield agent.
    """
    property_record = await db.get(Property, property_id)
    if property_record is None:
        raise LookupError(f"Property {property_id} not found.")

    booking_velocity = await get_booking_velocity(db, days_back=days_back)
    abandonment = await get_abandonment_rate(db, days_back=days_back)
    occupancy_gaps = await get_occupancy_gaps(
        db,
        property_id=property_id,
        window_days=window_days,
    )
    return FinancialExtractionContext(
        property_id=property_record.id,
        property_name=property_record.name,
        as_of_date=utc_now().date(),
        days_back=days_back,
        window_days=window_days,
        booking_velocity=booking_velocity,
        abandonment=abandonment,
        occupancy_gaps=occupancy_gaps,
    )
