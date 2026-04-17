"""Air-Gapped Calendar — 100% local Postgres, zero Streamline API calls.

All availability data is pre-synced to local tables by the Drift Sentry
(every 5 min) and the Streamline Availability Sync worker (every 5 min).
Request-time reads hit ONLY:
  - properties table  (rate_card JSONB, id, name, slug)
  - blocked_days table (reservation blocks)

This guarantees sub-20ms calendar loads regardless of Streamline API
health. Even during a full Streamline outage, the calendar remains
fully operational with data no more than 5 minutes stale.
"""

from __future__ import annotations

import calendar as cal_mod
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.blocked_day import BlockedDay
from backend.models.property import Property

router = APIRouter()

STATES_MAP: dict[str, dict[str, Any]] = {
    "cal-available": {"sid": 1, "css_class": "cal-available", "label": "Available",        "weight": 0, "is_available": True},
    "cal-booked":    {"sid": 2, "css_class": "cal-booked",    "label": "Reserved",         "weight": 1, "is_available": False},
    "cal-in":        {"sid": 3, "css_class": "cal-in",        "label": "Check In",         "weight": 2, "is_available": False},
    "cal-out":       {"sid": 4, "css_class": "cal-out",       "label": "Check Out",        "weight": 3, "is_available": True},
    "cal-inout":     {"sid": 5, "css_class": "cal-inout",     "label": "Turn-Around Date", "weight": 4, "is_available": True},
}
STATES = list(STATES_MAP.values())


def _build_rate_index(rate_card: Any) -> dict[str, float]:
    index: dict[str, float] = {}
    if not isinstance(rate_card, dict):
        return index
    rates = rate_card.get("rates")
    if not isinstance(rates, list):
        return index
    for entry in rates:
        if not isinstance(entry, dict):
            continue
        ds = entry.get("start_date")
        nightly = entry.get("nightly") or entry.get("nightly_rate") or entry.get("rate")
        if ds and nightly is not None:
            try:
                index[ds] = float(nightly)
            except (TypeError, ValueError):
                pass
    return index


def _build_day_states(
    blocked_days: list[BlockedDay],
    month_start: date,
    month_end: date,
) -> dict[str, str]:
    """Compute per-date CSS class from blocked_day boundaries.

    Streamline convention: ``end_date`` is the **last overnight stay**, NOT
    the checkout morning.  The real checkout day is ``end_date + 1``.

    Visual mapping:
      start_date            → cal-in   (check-in triangle)
      start_date+1 … end_date → cal-booked (solid reserved)
      end_date + 1          → cal-out  (check-out triangle)
      checkout == next check-in → cal-inout (turnaround)
    """
    checkins: set[str] = set()
    checkouts: set[str] = set()
    booked: set[str] = set()

    for bd in blocked_days:
        checkin_day = bd.start_date
        checkout_day = bd.end_date + timedelta(days=1)

        if month_start <= checkin_day <= month_end:
            checkins.add(checkin_day.isoformat())
        if month_start <= checkout_day <= month_end:
            checkouts.add(checkout_day.isoformat())

        mid = max(bd.start_date + timedelta(days=1), month_start)
        mid_end = min(bd.end_date, month_end)
        while mid <= mid_end:
            booked.add(mid.isoformat())
            mid += timedelta(days=1)

    day_states: dict[str, str] = {}
    d = month_start
    while d <= month_end:
        ds = d.isoformat()
        is_checkin = ds in checkins
        is_checkout = ds in checkouts
        is_booked = ds in booked

        if is_booked:
            css = "cal-booked"
        elif is_checkin and is_checkout:
            css = "cal-inout"
        elif is_checkin:
            css = "cal-in"
        elif is_checkout:
            css = "cal-out"
        else:
            css = "cal-available"

        day_states[ds] = css
        d += timedelta(days=1)

    return day_states


def _build_month_grid(
    prop: Property,
    year: int,
    month: int,
    rate_index: dict[str, float],
    day_states: dict[str, str],
) -> dict[str, Any]:
    _, days_in_month = cal_mod.monthrange(year, month)
    availability: dict[str, Any] = {}
    rates: dict[str, Any] = {}
    sid_int = int(prop.streamline_property_id or 0)

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        ds = d.isoformat()
        css = day_states.get(ds, "cal-available")
        state = STATES_MAP.get(css, STATES_MAP["cal-available"])
        availability[ds] = {
            "cid": 0,
            "date": ds,
            "sid": state["sid"],
            "state": state,
        }
        daily_rate = rate_index.get(ds, 0)
        rates[ds] = {
            "id": "",
            "cabin_id": str(prop.id),
            "streamline_id": sid_int,
            "date": ds,
            "daily_rate": daily_rate,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": None,
        }

    return {
        "year": year,
        "month": month,
        "availability": availability,
        "rates": rates,
        "states": STATES,
    }


async def _resolve_property(cabin_id: str, db: AsyncSession) -> Property:
    from uuid import UUID

    filters = []
    try:
        filters.append(Property.id == UUID(cabin_id))
    except ValueError:
        pass
    filters.append(Property.slug == cabin_id)
    if not filters:
        raise HTTPException(status_code=404, detail="Cabin not found")

    result = await db.execute(select(Property).where(or_(*filters)).limit(1))
    prop = result.scalars().first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Cabin not found")
    return prop


@router.get("/cabin/{cabin_id}")
async def get_cabin_calendar(
    cabin_id: str,
    months: int = Query(default=3, ge=1, le=24),
    start_date: str | None = Query(default=None),
    include_rates: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    prop = await _resolve_property(cabin_id, db)

    today = date.today()
    start_year = today.year
    start_month = today.month
    if start_date:
        try:
            sd = date.fromisoformat(start_date)
            start_year = sd.year
            start_month = sd.month
        except ValueError:
            pass

    rate_index = _build_rate_index(prop.rate_card) if include_rates else {}

    first_month_start = date(start_year, start_month, 1)
    last_m = start_month + months - 1
    last_y = start_year + (last_m - 1) // 12
    last_m = ((last_m - 1) % 12) + 1
    _, last_day = cal_mod.monthrange(last_y, last_m)
    last_month_end = date(last_y, last_m, last_day)

    blocked_result = await db.execute(
        select(BlockedDay).where(
            BlockedDay.property_id == prop.id,
            BlockedDay.end_date >= first_month_start,
            BlockedDay.start_date <= last_month_end,
        )
    )
    all_blocked = blocked_result.scalars().all()

    month_data: list[dict[str, Any]] = []
    for i in range(months):
        m = start_month + i
        y = start_year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        _, dim = cal_mod.monthrange(y, m)
        ms = date(y, m, 1)
        me = date(y, m, dim)
        day_states = _build_day_states(all_blocked, ms, me)
        month_data.append(_build_month_grid(prop, y, m, rate_index, day_states))

    return {
        "cabin_id": str(prop.id),
        "calendar_id": 0,
        "streamline_id": int(prop.streamline_property_id or 0),
        "months": month_data,
    }


@router.get("/states")
async def get_calendar_states() -> list[dict[str, Any]]:
    return STATES


@router.get("/available-cabins")
async def get_available_cabins(
    arrival_date: str = Query(...),
    departure_date: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        arr = date.fromisoformat(arrival_date)
        dep = date.fromisoformat(departure_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    props_result = await db.execute(
        select(Property).where(Property.is_active.is_(True))
    )
    properties = props_result.scalars().all()

    blocked_result = await db.execute(
        select(BlockedDay.property_id).where(
            BlockedDay.start_date < dep,
            BlockedDay.end_date > arr,
        ).distinct()
    )
    blocked_property_ids = {row[0] for row in blocked_result.all()}

    available_ids = [str(p.id) for p in properties if p.id not in blocked_property_ids]

    return {
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "total_cabins_checked": len(properties),
        "available_cabin_ids": available_ids,
        "details": {},
    }


@router.get("/availability-matrix/{year}/{month}")
async def get_availability_matrix(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    from fastapi.responses import JSONResponse
    import structlog
    logger = structlog.get_logger()

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
    if year < 2020 or year > 2030:
        raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")

    try:
        props_result = await db.execute(
            select(Property.id, Property.name, Property.slug)
            .where(Property.is_active.is_(True))
            .order_by(Property.name.asc())
        )
        properties = props_result.all()
    except Exception as exc:
        logger.error("availability_matrix_property_fetch_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"year": year, "month": month, "cabins": [], "states": STATES,
                      "partial": True, "error": "Property data temporarily unavailable"},
            headers={"Cache-Control": "no-cache"},
        )

    _, days_in_month = cal_mod.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    try:
        blocked_result = await db.execute(
            select(BlockedDay).where(
                BlockedDay.end_date >= month_start,
                BlockedDay.start_date <= month_end,
            )
        )
        all_blocked = blocked_result.scalars().all()
    except Exception as exc:
        logger.error("availability_matrix_blocked_fetch_failed", error=str(exc))
        all_blocked = []

    blocks_by_prop: dict[Any, list[BlockedDay]] = {}
    for bd in all_blocked:
        blocks_by_prop.setdefault(bd.property_id, []).append(bd)

    cabins = []
    skipped = 0
    for prop_id, prop_name, prop_slug in properties:
        if not prop_slug:
            skipped += 1
            continue
        try:
            prop_blocks = blocks_by_prop.get(prop_id, [])
            day_states = _build_day_states(prop_blocks, month_start, month_end)
            cabins.append({
                "cabin_id": str(prop_id),
                "cabin_title": prop_name,
                "cabin_slug": prop_slug,
                "calendar_id": None,
                "availability": day_states,
            })
        except Exception as exc:
            logger.warning("availability_matrix_cabin_skipped",
                           property_id=str(prop_id), name=prop_name, error=str(exc))
            skipped += 1

    if skipped:
        logger.info("availability_matrix_skipped_properties", count=skipped)

    payload = {
        "year": year,
        "month": month,
        "cabins": cabins,
        "states": STATES,
    }

    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "public, max-age=300, s-maxage=600"},
    )
