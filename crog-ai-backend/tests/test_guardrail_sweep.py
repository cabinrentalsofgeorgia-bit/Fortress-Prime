import datetime as dt
from decimal import Decimal

import pytest

from app.signals.calibration import CalibrationObservation
from app.signals.guardrail_sweep import (
    GuardedRangeCandidate,
    generated_guarded_range_event_history,
    sweep_guarded_range_candidates,
)
from app.signals.trade_triangles import EodBar


def _bar(index: int, *, open_: str, high: str, low: str, close: str) -> EodBar:
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000,
    )


def test_directional_close_suppresses_faded_intraday_breakout() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="10", high="12", low="9", close="9"),
    ]

    raw_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    guarded_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2, require_directional_close=True),
    )

    event_date = dt.date(2026, 1, 3)
    assert raw_history is not None
    assert guarded_history is not None
    assert raw_history.event_on(event_date) == 1
    assert guarded_history.event_on(event_date) is None
    assert guarded_history.state_as_of(event_date) == 0


def test_min_break_pct_suppresses_tiny_range_break() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="11", high="11.02", low="10", close="11.01"),
    ]

    raw_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    buffered_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(
            lookback_sessions=2,
            min_break_pct=Decimal("0.005"),
        ),
    )

    event_date = dt.date(2026, 1, 3)
    assert raw_history is not None
    assert buffered_history is not None
    assert raw_history.event_on(event_date) == 1
    assert buffered_history.event_on(event_date) is None


def test_debounce_suppresses_immediate_flip_after_event() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="11", high="12", low="10", close="12"),
        _bar(3, open_="10", high="10", low="8", close="8"),
    ]

    raw_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    debounced_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2, debounce_sessions=1),
    )

    flip_date = dt.date(2026, 1, 4)
    assert raw_history is not None
    assert debounced_history is not None
    assert raw_history.event_on(flip_date) == -1
    assert debounced_history.event_on(flip_date) is None
    assert debounced_history.state_as_of(flip_date) == 1


def test_guardrail_sweep_reports_event_reduction_and_ranks_quality() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="10", high="12", low="9", close="9"),
        _bar(3, open_="10", high="10", low="7", close="8"),
    ]
    observations = [
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 3),
            triangle_color="red",
            score=-15,
        ),
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 4),
            triangle_color="red",
            score=-15,
        ),
    ]

    results = sweep_guarded_range_candidates(
        observations,
        {"AA": bars},
        candidates=[
            GuardedRangeCandidate(lookback_sessions=2),
            GuardedRangeCandidate(lookback_sessions=2, require_directional_close=True),
        ],
    )

    assert results[0].require_directional_close is True
    assert results[0].exact_event_matches == 1
    assert results[0].exact_event_f1 == pytest.approx(2 / 3)
    assert results[0].generated_events == 1
    assert results[0].raw_range_generated_events == 2
    assert results[0].generated_event_reduction == 0.5


def test_atr_buffer_suppresses_break_that_is_small_for_recent_range() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="10", high="11", low="9", close="10"),
        _bar(2, open_="10", high="11.50", low="9.50", close="11.25"),
    ]

    raw_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    atr_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(
            lookback_sessions=2,
            atr_period_sessions=2,
            atr_multiplier=Decimal("0.50"),
        ),
    )

    event_date = dt.date(2026, 1, 3)
    assert raw_history is not None
    assert atr_history is not None
    assert raw_history.event_on(event_date) == 1
    assert atr_history.event_on(event_date) is None


def test_adaptive_cooldown_only_tightens_after_recent_symbol_churn() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="10", high="11", low="10", close="11"),
        _bar(2, open_="11", high="12", low="10", close="12"),
        _bar(3, open_="10", high="10", low="8", close="8"),
        _bar(4, open_="10", high="13", low="9", close="12"),
    ]

    raw_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    adaptive_history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(
            lookback_sessions=2,
            adaptive_cooldown_lookback_sessions=4,
            adaptive_cooldown_min_events=2,
            adaptive_cooldown_sessions=2,
        ),
    )

    churn_date = dt.date(2026, 1, 5)
    assert raw_history is not None
    assert adaptive_history is not None
    assert raw_history.event_on(churn_date) == 1
    assert adaptive_history.event_on(churn_date) is None
    assert adaptive_history.state_as_of(churn_date) == -1
