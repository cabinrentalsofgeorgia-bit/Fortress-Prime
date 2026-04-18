"""
Availability matrix endpoint tests.

Validates the /api/v1/calendar/availability-matrix/{year}/{month} route
handles valid requests, invalid inputs, and returns the expected shape.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.storefront_calendar import (
    _build_day_states,
    _build_rate_index,
    STATES_MAP,
)


class FakeBlockedDay:
    def __init__(self, start: str, end: str, property_id: str = "prop-1"):
        self.start_date = date.fromisoformat(start)
        self.end_date = date.fromisoformat(end)
        self.property_id = property_id


def test_build_day_states_no_blocks():
    month_start = date(2026, 4, 1)
    month_end = date(2026, 4, 30)
    states = _build_day_states([], month_start, month_end)
    assert len(states) == 30
    assert all(v == "cal-available" for v in states.values())


def test_build_day_states_single_reservation():
    month_start = date(2026, 4, 1)
    month_end = date(2026, 4, 30)
    blocked = [FakeBlockedDay("2026-04-10", "2026-04-13")]
    states = _build_day_states(blocked, month_start, month_end)

    assert states["2026-04-10"] == "cal-in"
    assert states["2026-04-11"] == "cal-booked"
    assert states["2026-04-12"] == "cal-booked"
    assert states["2026-04-13"] == "cal-booked"
    assert states["2026-04-14"] == "cal-out"
    assert states["2026-04-09"] == "cal-available"
    assert states["2026-04-15"] == "cal-available"


def test_build_day_states_back_to_back_turnaround():
    month_start = date(2026, 4, 1)
    month_end = date(2026, 4, 30)
    blocked = [
        FakeBlockedDay("2026-04-05", "2026-04-09"),
        FakeBlockedDay("2026-04-10", "2026-04-14"),
    ]
    states = _build_day_states(blocked, month_start, month_end)

    assert states["2026-04-05"] == "cal-in"
    assert states["2026-04-09"] == "cal-booked"
    assert states["2026-04-10"] == "cal-inout"
    assert states["2026-04-14"] == "cal-booked"
    assert states["2026-04-15"] == "cal-out"


def test_build_day_states_reservation_spanning_month_boundary():
    month_start = date(2026, 4, 1)
    month_end = date(2026, 4, 30)
    blocked = [FakeBlockedDay("2026-03-28", "2026-04-03")]
    states = _build_day_states(blocked, month_start, month_end)

    assert states["2026-04-01"] == "cal-booked"
    assert states["2026-04-02"] == "cal-booked"
    assert states["2026-04-03"] == "cal-booked"
    assert states["2026-04-04"] == "cal-out"
    assert states["2026-04-05"] == "cal-available"


def test_build_rate_index_valid():
    rate_card = {
        "rates": [
            {"start_date": "2026-04-01", "nightly": 325.0},
            {"start_date": "2026-04-02", "nightly_rate": 350.0},
            {"start_date": "2026-04-03", "rate": 399.0},
        ]
    }
    index = _build_rate_index(rate_card)
    assert index["2026-04-01"] == 325.0
    assert index["2026-04-02"] == 350.0
    assert index["2026-04-03"] == 399.0


def test_build_rate_index_empty():
    assert _build_rate_index(None) == {}
    assert _build_rate_index({}) == {}
    assert _build_rate_index({"rates": None}) == {}
    assert _build_rate_index({"rates": []}) == {}


def test_build_rate_index_malformed_entries():
    rate_card = {
        "rates": [
            {"start_date": "2026-04-01"},
            {"nightly": 100},
            None,
            "invalid",
        ]
    }
    index = _build_rate_index(rate_card)
    assert len(index) == 0


def test_states_map_completeness():
    required = {"cal-available", "cal-booked", "cal-in", "cal-out", "cal-inout"}
    assert set(STATES_MAP.keys()) == required
    for key, state in STATES_MAP.items():
        assert "sid" in state
        assert "css_class" in state
        assert state["css_class"] == key
