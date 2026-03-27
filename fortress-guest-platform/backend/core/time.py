"""
UTC time helpers for Fortress Prime.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Normalize database or test datetimes to timezone-aware UTC."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def combine_utc(day: date, clock: time) -> datetime:
    """Build a timezone-aware UTC datetime from a date and clock time."""
    return datetime.combine(day, clock, tzinfo=timezone.utc)
