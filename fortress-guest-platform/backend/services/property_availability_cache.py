"""
Local property availability cache builders.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from backend.services.reservation_engine import ReservationEngine

_RATE_HINT_ENGINE = ReservationEngine()
_CACHED_MONTH_COUNT = 12


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _month_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute_month = (year * 12) + (month - 1) + offset
    return absolute_month // 12, (absolute_month % 12) + 1


def _expand_blocked_dates(
    blocked_ranges: Iterable[dict[str, Any]],
    *,
    first_day: date,
    month_end_exclusive: date,
) -> set[date]:
    blocked_dates: set[date] = set()
    for blocked_range in blocked_ranges:
        start_date = _coerce_date(blocked_range.get("start_date"))
        end_date = _coerce_date(blocked_range.get("end_date"))
        if start_date is None or end_date is None:
            continue
        cursor = max(start_date, first_day)
        stop = min(end_date, month_end_exclusive)
        while cursor < stop:
            blocked_dates.add(cursor)
            cursor += timedelta(days=1)
    return blocked_dates


def build_property_availability_snapshot(
    *,
    property_id: str,
    property_slug: str,
    blocked_ranges: Iterable[dict[str, Any]],
    generated_at: datetime | None = None,
    anchor_date: date | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc)
    anchor = anchor_date or generated.date()
    first_month = date(anchor.year, anchor.month, 1)
    months: dict[str, dict[str, Any]] = {}

    for offset in range(_CACHED_MONTH_COUNT):
        year, month = _shift_month(first_month.year, first_month.month, offset)
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        month_end_exclusive = last_day + timedelta(days=1)
        blocked_dates = _expand_blocked_dates(
            blocked_ranges,
            first_day=first_day,
            month_end_exclusive=month_end_exclusive,
        )
        blocked_date_strings = [value.isoformat() for value in sorted(blocked_dates)]
        month_grid: dict[str, dict[str, Any]] = {}

        cursor = first_day
        while cursor <= last_day:
            iso_date = cursor.isoformat()
            is_blocked = cursor in blocked_dates
            nightly_rate, season_label, multiplier = _RATE_HINT_ENGINE._resolve_nightly_rate(
                cursor,
                base_rate=_RATE_HINT_ENGINE.DEFAULT_BASE_RATE,
            )
            month_grid[iso_date] = {
                "date": iso_date,
                "status": "blocked" if is_blocked else "available",
                "available": not is_blocked,
                "nightly_rate": None if is_blocked else float(nightly_rate),
                "season": season_label,
                "multiplier": float(multiplier),
            }
            cursor += timedelta(days=1)

        months[_month_key(year, month)] = {
            "property_id": property_id,
            "property_slug": property_slug,
            "month": month,
            "year": year,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "blocked_dates": blocked_date_strings,
            "blocked_dates_count": len(blocked_date_strings),
            "available_dates_count": max(0, last_day_num - len(blocked_date_strings)),
            "generated_at": generated.isoformat(),
            "month_grid": month_grid,
            "pricing_source": "local_ledger",
            "availability_source": "streamline_property_cache",
        }

    last_year, last_month = _shift_month(first_month.year, first_month.month, _CACHED_MONTH_COUNT - 1)
    _, last_month_day = calendar.monthrange(last_year, last_month)
    return {
        "generated_at": generated.isoformat(),
        "source": "streamline_vrs",
        "window_start": first_month.isoformat(),
        "window_end": date(last_year, last_month, last_month_day).isoformat(),
        "months": months,
    }


def get_property_availability_month(
    snapshot: dict[str, Any] | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    if "month_grid" in snapshot and "month" in snapshot and "year" in snapshot:
        return snapshot

    current_date = datetime.now(timezone.utc).date()
    target_year = year or current_date.year
    target_month = month or current_date.month
    months = snapshot.get("months")
    if not isinstance(months, dict):
        return None

    candidate = months.get(_month_key(target_year, target_month))
    if isinstance(candidate, dict):
        return candidate
    return None
