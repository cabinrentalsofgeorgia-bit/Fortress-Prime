from __future__ import annotations

from datetime import date, datetime, timezone

from backend.services.property_availability_cache import (
    build_property_availability_snapshot,
    get_property_availability_month,
)


def test_build_property_availability_snapshot_caches_month_grid() -> None:
    snapshot = build_property_availability_snapshot(
        property_id="property-123",
        property_slug="ridge-line-lodge",
        blocked_ranges=[
            {"start_date": date(2026, 3, 10), "end_date": date(2026, 3, 13)},
        ],
        generated_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        anchor_date=date(2026, 3, 24),
    )

    march = get_property_availability_month(snapshot, year=2026, month=3)

    assert march is not None
    assert march["property_id"] == "property-123"
    assert march["property_slug"] == "ridge-line-lodge"
    assert march["availability_source"] == "streamline_property_cache"
    assert march["blocked_dates"] == ["2026-03-10", "2026-03-11", "2026-03-12"]
    assert march["month_grid"]["2026-03-10"]["available"] is False
    assert march["month_grid"]["2026-03-13"]["available"] is True


def test_get_property_availability_month_returns_none_for_missing_month() -> None:
    snapshot = build_property_availability_snapshot(
        property_id="property-123",
        property_slug="ridge-line-lodge",
        blocked_ranges=[],
        generated_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        anchor_date=date(2026, 3, 24),
    )

    assert get_property_availability_month(snapshot, year=2027, month=6) is None
