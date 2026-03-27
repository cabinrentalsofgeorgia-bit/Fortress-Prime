"""
Build Channex-oriented availability + rate payloads from local PostgreSQL state.

Uses the same occupancy definition as :meth:`ReservationEngine.get_blocked_dates_for_month`
(blocked_days, occupying reservations, active non-expired holds).

The HTTP shape is versioned (`schema`) so operators can align ``CHANNEX_AVAILABILITY_PATH``
with the real Channex (or proxy) API without changing Kafka contracts.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Property, Reservation, ReservationHold
from backend.models.blocked_day import BlockedDay
from backend.services.reservation_engine import OCCUPYING_AVAILABILITY_STATUSES, ReservationEngine
from backend.core.time import utc_now

logger = structlog.get_logger(service="channex_calendar_export")

# Stored on ``Property.ota_metadata`` — set per property when mapped in Channex.
CHANNEX_LISTING_METADATA_KEY = "channex_listing_id"

DEFAULT_EXPORT_HORIZON_DAYS = 548  # ~18 months

_reservation_engine = ReservationEngine()


def _missing_runtime_table(exc: ProgrammingError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "does not exist" in message or "undefinedtable" in message


def _property_base_rate(prop: Property) -> Decimal:
    rc = prop.rate_card or {}
    if isinstance(rc, dict):
        for key in ("base_nightly", "default_rate", "base_rate"):
            raw = rc.get(key)
            if raw is not None:
                try:
                    return Decimal(str(raw)).quantize(Decimal("0.01"))
                except Exception:
                    break
    return _reservation_engine.DEFAULT_BASE_RATE


def channex_listing_id_for_property(prop: Property) -> str | None:
    meta = prop.ota_metadata or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get(CHANNEX_LISTING_METADATA_KEY)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


async def load_blocked_dates_window(
    db: AsyncSession,
    property_id: UUID,
    window_start: date,
    window_end_exclusive: date,
) -> set[date]:
    """All calendar dates in ``[window_start, window_end_exclusive)`` that are not sellable."""
    blocked: set[date] = set()

    def add_range(start: date, end: date) -> None:
        cursor = max(start, window_start)
        stop = min(end, window_end_exclusive)
        while cursor < stop:
            blocked.add(cursor)
            cursor += timedelta(days=1)

    try:
        bd_rows = (
            await db.execute(
                select(BlockedDay.start_date, BlockedDay.end_date).where(
                    and_(
                        BlockedDay.property_id == property_id,
                        BlockedDay.start_date < window_end_exclusive,
                        BlockedDay.end_date > window_start,
                    )
                )
            )
        ).all()
        for s, e in bd_rows:
            add_range(s, e)
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("channex_export_blocked_days_table_missing")
        await db.rollback()

    res_rows = (
        await db.execute(
            select(Reservation.check_in_date, Reservation.check_out_date).where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(OCCUPYING_AVAILABILITY_STATUSES),
                    Reservation.check_in_date < window_end_exclusive,
                    Reservation.check_out_date > window_start,
                )
            )
        )
    ).all()
    for s, e in res_rows:
        add_range(s, e)

    now = utc_now()
    try:
        hold_rows = (
            await db.execute(
                select(ReservationHold.check_in_date, ReservationHold.check_out_date).where(
                    and_(
                        ReservationHold.property_id == property_id,
                        ReservationHold.status == "active",
                        ReservationHold.expires_at > now,
                        ReservationHold.check_in_date < window_end_exclusive,
                        ReservationHold.check_out_date > window_start,
                    )
                )
            )
        ).all()
        for s, e in hold_rows:
            add_range(s, e)
    except ProgrammingError as exc:
        if not _missing_runtime_table(exc):
            raise
        logger.warning("channex_export_reservation_holds_table_missing")
        await db.rollback()

    return blocked


def build_daily_rows(
    *,
    window_start: date,
    window_end_exclusive: date,
    blocked: set[date],
    base_rate: Decimal,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = window_start
    while cursor < window_end_exclusive:
        is_blocked = cursor in blocked
        nightly: float | None
        if is_blocked:
            nightly = None
        else:
            rate, _, _ = _reservation_engine._resolve_nightly_rate(cursor, base_rate=base_rate)
            nightly = float(rate)
        rows.append(
            {
                "date": cursor.isoformat(),
                "availability": "unavailable" if is_blocked else "available",
                "available": not is_blocked,
                "nightly_rate": nightly,
                "currency": "USD",
            }
        )
        cursor += timedelta(days=1)
    return rows


async def build_channex_availability_document(
    db: AsyncSession,
    property_id: UUID,
    *,
    horizon_days: int = DEFAULT_EXPORT_HORIZON_DAYS,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Returns ``(document, skip_reason)``. If ``skip_reason`` is set, do not POST to Channex.
    """
    prop = await db.get(Property, property_id)
    if prop is None:
        return None, "property_not_found"

    listing_id = channex_listing_id_for_property(prop)
    if not listing_id:
        return None, "no_channex_listing_id"

    today = date.today()
    window_end = today + timedelta(days=max(1, horizon_days))
    blocked = await load_blocked_dates_window(db, property_id, today, window_end)
    base_rate = _property_base_rate(prop)
    days = build_daily_rows(
        window_start=today,
        window_end_exclusive=window_end,
        blocked=blocked,
        base_rate=base_rate,
    )

    document: dict[str, Any] = {
        "schema": "fortress.channex_availability.v1",
        "channex_listing_id": listing_id,
        "fortress_property_id": str(property_id),
        "property_slug": prop.slug,
        "generated_at": utc_now().isoformat().replace("+00:00", "Z"),
        "window_start": today.isoformat(),
        "window_end_exclusive": window_end.isoformat(),
        "days": days,
        "summary": {
            "blocked_night_count": len(blocked),
            "total_nights": len(days),
        },
    }
    return document, None


def push_url_for_listing(base_url: str, path_template: str, listing_id: str) -> str:
    """Resolve POST target; ``path_template`` may include ``{listing_id}``."""
    base = base_url.strip().rstrip("/")
    path = path_template.strip()
    if not path.startswith("/"):
        path = "/" + path
    if "{listing_id}" in path:
        return f"{base}{path.format(listing_id=listing_id)}"
    return f"{base}{path}"
