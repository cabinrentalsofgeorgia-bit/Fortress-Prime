import datetime as dt
from decimal import Decimal

from app.signals.trade_triangles import EodBar
from app.signals.whipsaw_risk import build_symbol_whipsaw_risk


def _bar(day: int, *, high: str, low: str, close: str) -> EodBar:
    close_decimal = Decimal(close)
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, day),
        open=close_decimal,
        high=Decimal(high),
        low=Decimal(low),
        close=close_decimal,
        volume=1000,
    )


def test_build_symbol_whipsaw_risk_flags_fast_reversals_and_outcomes() -> None:
    bars = [
        _bar(1, high="11", low="9", close="10"),
        _bar(2, high="12", low="10", close="11"),
        _bar(3, high="12", low="10", close="11"),
        _bar(4, high="14", low="12", close="13"),
        _bar(5, high="9", low="7", close="8"),
        _bar(6, high="16", low="14", close="15"),
        _bar(7, high="17", low="15", close="16"),
    ]

    payload = build_symbol_whipsaw_risk(
        ticker="AA",
        bars=bars,
        sessions=7,
        whipsaw_window_sessions=2,
        outcome_horizon_sessions=1,
    )

    assert payload["event_count"] == 3
    assert payload["whipsaw_count"] == 2
    assert payload["whipsaw_rate"] == 1
    assert payload["risk_level"] == "high"
    assert payload["outcome"]["evaluated_events"] == 3
    assert payload["recent_events"][0]["event_date"] == dt.date(2026, 1, 6)
    assert payload["recent_events"][0]["is_whipsaw"] is True
