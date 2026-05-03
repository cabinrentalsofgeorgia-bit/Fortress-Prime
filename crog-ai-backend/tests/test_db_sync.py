import datetime as dt
from decimal import Decimal
from uuid import UUID

from app.signals.db_preview import SignalTransitionPreview, preview_from_snapshot
from app.signals.db_sync import signal_score_params, signal_transition_params
from app.signals.trade_triangles import EodBar, latest_triangle_snapshot
from scripts.sync_signal_scores import _fresh_cutoff, _is_fresh_enough


def test_freshness_window_uses_reference_date() -> None:
    reference_date = dt.date(2026, 4, 24)

    assert _fresh_cutoff(reference_date, 5) == dt.date(2026, 4, 19)
    assert _is_fresh_enough(
        dt.date(2026, 4, 19),
        reference_date=reference_date,
        max_stale_days=5,
    )
    assert not _is_fresh_enough(
        dt.date(2026, 4, 18),
        reference_date=reference_date,
        max_stale_days=5,
    )


def test_signal_score_params_match_upsert_shape() -> None:
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
    parameter_set_id = UUID("11111111-1111-1111-1111-111111111111")

    params = signal_score_params(preview, parameter_set_id=parameter_set_id)

    assert params == {
        "ticker": "AA",
        "bar_date": "2026-03-05",
        "parameter_set_id": parameter_set_id,
        "monthly_state": 1,
        "weekly_state": 1,
        "daily_state": 1,
        "momentum_state": 0,
        "monthly_channel_high": Decimal("162"),
        "monthly_channel_low": Decimal("99"),
        "weekly_channel_high": Decimal("162"),
        "weekly_channel_low": Decimal("147"),
        "daily_channel_high": Decimal("162"),
        "daily_channel_low": Decimal("159"),
        "macd_histogram": None,
    }


def test_signal_transition_params_wrap_json_states() -> None:
    preview = SignalTransitionPreview(
        ticker="AA",
        parameter_set_name="dochia_v0_estimated",
        transition_type="breakout_bullish",
        from_score=40,
        to_score=80,
        from_bar_date="2026-03-01",
        to_bar_date="2026-03-05",
        from_states={"monthly": 0, "weekly": 1, "daily": 1, "momentum": 0},
        to_states={"monthly": 1, "weekly": 1, "daily": 1, "momentum": 0},
        notes="monthly triangle green",
    )
    parameter_set_id = UUID("11111111-1111-1111-1111-111111111111")

    params = signal_transition_params(preview, parameter_set_id=parameter_set_id)

    assert params["ticker"] == "AA"
    assert params["parameter_set_id"] == parameter_set_id
    assert params["transition_type"] == "breakout_bullish"
    assert params["from_states"].obj == {
        "monthly": 0,
        "weekly": 1,
        "daily": 1,
        "momentum": 0,
    }
    assert params["to_states"].obj["monthly"] == 1
