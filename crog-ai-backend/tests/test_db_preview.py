import datetime as dt
from decimal import Decimal

from app.signals.db_preview import (
    eod_row_to_bar,
    normalize_psycopg_url,
    preview_from_snapshot,
    transition_previews_from_snapshot,
)
from app.signals.trade_triangles import EodBar, latest_triangle_snapshot


def test_normalize_psycopg_url_accepts_sqlalchemy_scheme() -> None:
    assert (
        normalize_psycopg_url("postgresql+psycopg://user:pass@localhost/db")
        == "postgresql://user:pass@localhost/db"
    )


def test_eod_row_to_bar_preserves_decimal_fields() -> None:
    row = {
        "ticker": "AA",
        "bar_date": dt.date(2026, 1, 2),
        "open": Decimal("10.1000"),
        "high": Decimal("11.2000"),
        "low": Decimal("9.9000"),
        "close": Decimal("10.8000"),
        "volume": 1234,
    }

    bar = eod_row_to_bar(row)

    assert bar.ticker == "AA"
    assert bar.high == Decimal("11.2000")
    assert bar.volume == 1234


def test_preview_from_snapshot_matches_signal_score_shape() -> None:
    bars = [
        EodBar(
            ticker="AA",
            bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(100 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=1000,
        )
        for index in range(64)
    ]
    snapshot = latest_triangle_snapshot(bars)

    preview = preview_from_snapshot(
        snapshot,
        parameter_set_name="dochia_v0_estimated",
        monthly_weight=40,
        weekly_weight=25,
        daily_weight=15,
        momentum_weight=20,
    )

    assert preview.ticker == "AA"
    assert preview.bar_date == "2026-03-05"
    assert preview.monthly_state == 1
    assert preview.weekly_state == 1
    assert preview.daily_state == 1
    assert preview.momentum_state == 0
    assert preview.composite_score == 80
    assert preview.as_json_dict()["daily_channel_high"] == "162"


def test_transition_previews_replay_triangle_state_changes() -> None:
    bars = [
        EodBar(
            ticker="AA",
            bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(100 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=1000,
        )
        for index in range(64)
    ]
    snapshot = latest_triangle_snapshot(bars)

    previews = transition_previews_from_snapshot(
        snapshot,
        parameter_set_name="dochia_v0_estimated",
        monthly_weight=40,
        weekly_weight=25,
        daily_weight=15,
        momentum_weight=20,
    )

    assert [item.to_score for item in previews] == [15, 40, 80]
    assert previews[0].transition_type == "exit_to_reentry"
    assert previews[-1].to_states == {
        "monthly": 1,
        "weekly": 1,
        "daily": 1,
        "momentum": 0,
    }
    assert previews[-1].to_bar_date == "2026-03-05"
