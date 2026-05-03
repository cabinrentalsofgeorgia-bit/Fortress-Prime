import datetime as dt
from decimal import Decimal

from app.signals.calibration import CalibrationObservation
from app.signals.calibration_sweep import (
    generated_daily_event_history,
    sweep_daily_event_candidates,
)
from app.signals.trade_triangles import EodBar


def _bar(index: int, *, open_: int, high: int, low: int, close: int) -> EodBar:
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000,
    )


def test_range_trigger_uses_intraday_break_when_close_does_not_break() -> None:
    bars = [
        _bar(0, open_=10, high=10, low=9, close=10),
        _bar(1, open_=11, high=11, low=10, close=11),
        _bar(2, open_=10, high=12, low=9, close=10),
    ]

    close_history = generated_daily_event_history(
        bars,
        lookback_sessions=2,
        trigger_mode="close",
    )
    range_history = generated_daily_event_history(
        bars,
        lookback_sessions=2,
        trigger_mode="range",
    )

    event_date = dt.date(2026, 1, 3)
    assert close_history is not None
    assert range_history is not None
    assert close_history.event_on(event_date) is None
    assert range_history.event_on(event_date) == 1
    assert range_history.state_as_of(event_date) == 1


def test_sweep_ranks_best_exact_event_candidate_first() -> None:
    bars = [
        _bar(0, open_=10, high=10, low=9, close=10),
        _bar(1, open_=11, high=11, low=10, close=11),
        _bar(2, open_=10, high=12, low=9, close=10),
        _bar(3, open_=9, high=9, low=7, close=8),
    ]
    observations = [
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 3),
            triangle_color="green",
            score=15,
        ),
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 4),
            triangle_color="red",
            score=-15,
        ),
    ]

    results = sweep_daily_event_candidates(
        observations,
        {"AA": bars},
        lookbacks=[2],
        trigger_modes=["close", "range"],
    )

    assert [(result.lookback_sessions, result.trigger_mode) for result in results] == [
        (2, "range"),
        (2, "close"),
    ]
    assert results[0].exact_event_matches == 2
    assert results[0].exact_event_f1 == 1
    assert results[1].exact_event_matches == 1
