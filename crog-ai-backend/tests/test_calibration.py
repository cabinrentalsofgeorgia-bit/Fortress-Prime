import datetime as dt
from decimal import Decimal

from app.signals.calibration import (
    CalibrationObservation,
    CalibrationWeights,
    evaluate_daily_calibration,
    generated_state_history,
)
from app.signals.trade_triangles import EodBar


def _bar(index: int, close: int) -> EodBar:
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close - 1),
        close=Decimal(close),
        volume=1000,
    )


def test_generated_state_history_carries_daily_triangle_state() -> None:
    bars = [_bar(0, 10), _bar(1, 11), _bar(2, 12), _bar(3, 13), _bar(4, 14)]
    weights = CalibrationWeights(monthly=40, weekly=25, daily=15, momentum=20)

    history = generated_state_history(bars, weights=weights)

    assert history is not None
    latest = history.as_of(dt.date(2026, 1, 5))
    assert latest is not None
    assert latest.daily_state == 1
    assert latest.composite_score == 15


def test_evaluate_daily_calibration_reports_confusion_and_score_error() -> None:
    bars = [_bar(0, 10), _bar(1, 11), _bar(2, 12), _bar(3, 13), _bar(4, 14)]
    observations = [
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 4),
            triangle_color="green",
            score=15,
        ),
        CalibrationObservation(
            ticker="AA",
            trading_day=dt.date(2026, 1, 5),
            triangle_color="red",
            score=-15,
        ),
        CalibrationObservation(
            ticker="MISSING",
            trading_day=dt.date(2026, 1, 5),
            triangle_color="green",
            score=15,
        ),
    ]

    result = evaluate_daily_calibration(
        observations,
        {"AA": bars},
        parameter_set_name="dochia_v0_estimated",
        weights=CalibrationWeights(monthly=40, weekly=25, daily=15, momentum=20),
    )

    assert result.total_observations == 3
    assert result.covered_observations == 2
    assert result.matches == 1
    assert result.accuracy == 0.5
    assert result.confusion["green"]["green"] == 1
    assert result.confusion["green"]["missing"] == 1
    assert result.confusion["red"]["green"] == 1
    assert result.score_mae == 15
