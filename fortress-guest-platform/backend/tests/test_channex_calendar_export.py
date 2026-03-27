from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.channex_calendar_export import (
    build_daily_rows,
    push_url_for_listing,
)


def test_build_daily_rows_marks_blocked_and_rates_available() -> None:
    start = date(2026, 6, 1)
    end = date(2026, 6, 5)
    blocked = {date(2026, 6, 2), date(2026, 6, 3)}
    from decimal import Decimal

    rows = build_daily_rows(
        window_start=start,
        window_end_exclusive=end,
        blocked=blocked,
        base_rate=Decimal("200.00"),
    )
    assert len(rows) == 4
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["available"] is True
    assert rows[0]["nightly_rate"] is not None
    assert rows[1]["available"] is False
    assert rows[1]["nightly_rate"] is None
    assert rows[1]["availability"] == "unavailable"


@pytest.mark.parametrize(
    ("path", "expected_suffix"),
    [
        ("/api/v1/listings/{listing_id}/calendar", "/api/v1/listings/L123/calendar"),
        ("/api/v1/channel/availability", "/api/v1/channel/availability"),
    ],
)
def test_push_url_for_listing(path: str, expected_suffix: str) -> None:
    url = push_url_for_listing("https://api.example.com", path, "L123")
    assert url == "https://api.example.com" + expected_suffix
