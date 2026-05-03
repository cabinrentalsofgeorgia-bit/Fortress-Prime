import datetime as dt
from decimal import Decimal

from app.signals.chart_repository import build_symbol_chart
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


def _range_bar(index: int, *, open_: int, high: int, low: int, close: int) -> EodBar:
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000,
    )


def test_build_symbol_chart_returns_visible_bars_channels_and_events() -> None:
    bars = [_bar(index, 100 + index) for index in range(70)]

    chart = build_symbol_chart(ticker="AA", bars=bars, sessions=10)

    assert chart["ticker"] == "AA"
    assert chart["sessions"] == 10
    assert len(chart["bars"]) == 10
    assert chart["bars"][0]["bar_date"] == dt.date(2026, 3, 2)
    assert chart["bars"][0]["daily_channel_high"] == Decimal("159")
    assert {event["timeframe"] for event in chart["events"]} == {"monthly"}
    assert chart["events"][0]["state"] == "green"


def test_build_symbol_chart_uses_range_daily_events_for_v0_2_candidate() -> None:
    bars = [
        _range_bar(0, open_=10, high=10, low=9, close=10),
        _range_bar(1, open_=11, high=11, low=10, close=11),
        _range_bar(2, open_=12, high=12, low=11, close=12),
        _range_bar(3, open_=11, high=13, low=11, close=12),
    ]

    production_chart = build_symbol_chart(ticker="AA", bars=bars, sessions=4)
    candidate_chart = build_symbol_chart(
        ticker="AA",
        bars=bars,
        sessions=4,
        parameter_set="dochia_v0_2_range_daily",
    )

    assert production_chart["parameter_set_name"] == "dochia_v0_estimated"
    assert production_chart["daily_trigger_mode"] == "close"
    assert production_chart["events"] == []
    assert candidate_chart["parameter_set_name"] == "dochia_v0_2_range_daily"
    assert candidate_chart["daily_trigger_mode"] == "range"
    assert candidate_chart["events"][0]["timeframe"] == "daily"
    assert candidate_chart["events"][0]["state"] == "green"
    assert candidate_chart["events"][0]["trigger_price"] == Decimal("13")
