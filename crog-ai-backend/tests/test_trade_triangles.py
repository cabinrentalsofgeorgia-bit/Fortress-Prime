import datetime as dt
from decimal import Decimal

import pytest

from app.signals.trade_triangles import (
    EodBar,
    TriangleState,
    TriangleTimeframe,
    TriangleTriggerMode,
    detect_triangle_events,
    latest_triangle_snapshot,
)


def _bar(day: int, close: str, *, high: str | None = None, low: str | None = None) -> EodBar:
    close_value = Decimal(close)
    high_value = Decimal(high) if high is not None else close_value
    low_value = Decimal(low) if low is not None else close_value
    return EodBar(
        ticker="TEST",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=day),
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=1000,
    )


def test_daily_green_break_uses_prior_three_sessions_only() -> None:
    bars = [
        _bar(0, "10", high="10", low="9"),
        _bar(1, "11", high="11", low="10"),
        _bar(2, "12", high="12", low="11"),
        _bar(3, "13", high="13", low="12"),
    ]

    events = detect_triangle_events(bars, TriangleTimeframe.DAILY)

    assert len(events) == 1
    assert events[0].state is TriangleState.GREEN
    assert events[0].channel_high == Decimal("12")
    assert events[0].channel_low == Decimal("9")
    assert "broke above" in events[0].reason


def test_daily_range_trigger_uses_intraday_high_low_breaks() -> None:
    bars = [
        _bar(0, "10", high="10", low="9"),
        _bar(1, "11", high="11", low="10"),
        _bar(2, "12", high="12", low="11"),
        _bar(3, "11", high="13", low="10"),
    ]

    close_events = detect_triangle_events(bars, TriangleTimeframe.DAILY)
    range_events = detect_triangle_events(
        bars,
        TriangleTimeframe.DAILY,
        trigger_mode=TriangleTriggerMode.RANGE,
    )

    assert close_events == ()
    assert len(range_events) == 1
    assert range_events[0].state is TriangleState.GREEN
    assert range_events[0].trigger_price == Decimal("13")
    assert "high 13" in range_events[0].reason


def test_daily_red_reversal_is_state_change_not_repeated_noise() -> None:
    bars = [
        _bar(0, "10", high="10", low="9"),
        _bar(1, "11", high="11", low="10"),
        _bar(2, "12", high="12", low="11"),
        _bar(3, "13", high="13", low="12"),
        _bar(4, "14", high="14", low="13"),
        _bar(5, "15", high="15", low="14"),
        _bar(6, "8", high="9", low="8"),
        _bar(7, "7", high="8", low="7"),
    ]

    events = detect_triangle_events(bars, TriangleTimeframe.DAILY)

    assert [event.state for event in events] == [TriangleState.GREEN, TriangleState.RED]
    assert events[-1].channel_low == Decimal("12")
    assert "broke below" in events[-1].reason


def test_snapshot_returns_carried_states_and_schema_compatible_score() -> None:
    bars = [
        _bar(index, str(100 + index), high=str(100 + index), low=str(99 + index))
        for index in range(64)
    ]

    snapshot = latest_triangle_snapshot(bars)

    assert snapshot.daily_state is TriangleState.GREEN
    assert snapshot.weekly_state is TriangleState.GREEN
    assert snapshot.monthly_state is TriangleState.GREEN
    assert snapshot.state_tuple == (1, 1, 1)
    assert snapshot.composite_score() == 80
    assert snapshot.monthly_channel_high == Decimal("162")


def test_rejects_mixed_ticker_inputs() -> None:
    bars = [
        _bar(0, "10"),
        EodBar(
            ticker="OTHER",
            bar_date=dt.date(2026, 1, 2),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("9"),
            close=Decimal("9"),
        ),
    ]

    with pytest.raises(ValueError, match="exactly one ticker"):
        detect_triangle_events(bars, TriangleTimeframe.DAILY)
