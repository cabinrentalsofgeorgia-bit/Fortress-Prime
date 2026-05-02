import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.signals import get_signal_store
from app.main import create_app

PARAMETER_SET_ID = UUID("11111111-1111-1111-1111-111111111111")
TRANSITION_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSignalStore:
    def latest_scores(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
    ) -> list[dict[str, Any]]:
        if ticker == "MISSING":
            return []
        row = {
            "ticker": ticker or "AA",
            "bar_date": dt.date(2026, 4, 24),
            "parameter_set_id": PARAMETER_SET_ID,
            "parameter_set_name": "dochia_v0_estimated",
            "dochia_version": "v0",
            "monthly_state": 1,
            "weekly_state": 1,
            "daily_state": 1,
            "momentum_state": 0,
            "composite_score": 80,
            "computed_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
            "monthly_channel_high": Decimal("75.6999"),
            "monthly_channel_low": Decimal("55.0400"),
            "weekly_channel_high": Decimal("75.6999"),
            "weekly_channel_low": Decimal("63.0300"),
            "daily_channel_high": Decimal("69.3750"),
            "daily_channel_low": Decimal("65.1500"),
        }
        if min_score is not None and row["composite_score"] < min_score:
            return []
        if max_score is not None and row["composite_score"] > max_score:
            return []
        return [row][:limit]

    def recent_transitions(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        transition_type: str | None = None,
        since: dt.date | None = None,
        lookback_days: int | None = None,
    ) -> list[dict[str, Any]]:
        row = {
            "id": TRANSITION_ID,
            "ticker": ticker or "AA",
            "parameter_set_name": "dochia_v0_estimated",
            "transition_type": transition_type or "breakout_bullish",
            "from_score": 50,
            "to_score": 80,
            "from_bar_date": dt.date(2026, 4, 14),
            "to_bar_date": since or dt.date(2026, 4, 22),
            "from_states": {"monthly": 1, "weekly": 1, "daily": -1, "momentum": 0},
            "to_states": {"monthly": 1, "weekly": 1, "daily": 1, "momentum": 0},
            "detected_at": dt.datetime(2026, 5, 2, 12, 1, tzinfo=dt.UTC),
            "acknowledged_by_user_id": None,
            "acknowledged_at": None,
            "notes": f"lookback={lookback_days}",
        }
        return [row][:limit]

    def watchlist_candidates(self, *, limit: int) -> dict[str, list[dict[str, Any]]]:
        row = {
            "ticker": "AA",
            "bar_date": dt.date(2026, 4, 24),
            "parameter_set_name": "dochia_v0_estimated",
            "monthly_state": 1,
            "weekly_state": 1,
            "daily_state": 1,
            "momentum_state": 0,
            "composite_score": 80,
            "latest_transition_type": "breakout_bullish",
            "latest_transition_bar_date": dt.date(2026, 4, 22),
            "latest_transition_notes": "daily triangle green",
            "sector": "Materials",
            "watchlist_signal_count": 4,
            "watchlist_last_signal_at": dt.datetime(2026, 2, 12, 17, 0, tzinfo=dt.UTC),
            "legacy_action": "BUY",
            "legacy_signal_type": "Technical",
            "legacy_confidence_score": 87,
            "legacy_price_target": Decimal("84.50"),
            "legacy_signal_at": dt.datetime(2026, 2, 12, 17, 1, tzinfo=dt.UTC),
        }
        return {
            "bullish_alignment": [row][:limit],
            "risk_alignment": [],
            "reentry": [row][:limit],
            "mixed_timeframes": [],
        }

    def daily_calibration(
        self,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
        ticker: str | None = None,
        parameter_set: str | None = None,
        top_tickers: int = 20,
    ) -> dict[str, Any]:
        return {
            "parameter_set_name": parameter_set or "dochia_v0_estimated",
            "generated_at": dt.datetime(2026, 5, 2, 12, 2, tzinfo=dt.UTC).isoformat(),
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "total_observations": 3,
            "covered_observations": 2,
            "exact_bar_observations": 2,
            "missing_observations": 1,
            "neutral_generated_observations": 0,
            "matches": 1,
            "accuracy": 0.5,
            "coverage_rate": 2 / 3,
            "exact_coverage_rate": 2 / 3,
            "green_precision": 0.5,
            "green_recall": 1.0,
            "red_precision": None,
            "red_recall": 0.0,
            "score_mae": 15.0,
            "score_rmse": 21.21,
            "confusion": {
                "green": {"green": 1, "red": 0, "neutral": 0, "missing": 1},
                "red": {"green": 1, "red": 0, "neutral": 0, "missing": 0},
            },
            "top_tickers": [
                {
                    "ticker": ticker or "AA",
                    "observations": 2,
                    "covered_observations": 2,
                    "exact_bar_observations": 2,
                    "matches": 1,
                    "accuracy": 0.5,
                    "score_mae": 15.0,
                }
            ][:top_tickers],
        }

    def symbol_chart(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
    ) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "sessions": 2,
            "bars": [
                {
                    "ticker": ticker,
                    "bar_date": dt.date(2026, 4, 23),
                    "open": Decimal("66.00"),
                    "high": Decimal("69.00"),
                    "low": Decimal("65.00"),
                    "close": Decimal("68.00"),
                    "volume": 1000,
                    "daily_channel_high": Decimal("67.00"),
                    "daily_channel_low": Decimal("64.00"),
                    "weekly_channel_high": Decimal("70.00"),
                    "weekly_channel_low": Decimal("60.00"),
                    "monthly_channel_high": Decimal("75.00"),
                    "monthly_channel_low": Decimal("55.00"),
                },
                {
                    "ticker": ticker,
                    "bar_date": as_of or dt.date(2026, 4, 24),
                    "open": Decimal("68.00"),
                    "high": Decimal("70.00"),
                    "low": Decimal("66.00"),
                    "close": Decimal("69.00"),
                    "volume": 1200,
                    "daily_channel_high": Decimal("69.00"),
                    "daily_channel_low": Decimal("65.00"),
                    "weekly_channel_high": Decimal("70.00"),
                    "weekly_channel_low": Decimal("61.00"),
                    "monthly_channel_high": Decimal("75.00"),
                    "monthly_channel_low": Decimal("55.00"),
                },
            ],
            "events": [
                {
                    "ticker": ticker,
                    "timeframe": "daily",
                    "state": "green",
                    "bar_date": dt.date(2026, 4, 24),
                    "trigger_price": Decimal("69.00"),
                    "channel_high": Decimal("68.50"),
                    "channel_low": Decimal("65.00"),
                    "lookback_sessions": 3,
                    "reason": "close 69.00 broke above prior 3-session high 68.50",
                }
            ],
        }


def test_latest_scores_endpoint_returns_scanner_rows() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/latest?limit=1&min_score=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["ticker"] == "AA"
    assert payload[0]["composite_score"] == 80
    assert payload[0]["state_labels"]["monthly"] == "green"


def test_transitions_endpoint_returns_recent_alert_rows() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/transitions?transition_type=exit_to_reentry&limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["transition_type"] == "exit_to_reentry"
    assert payload[0]["from_score"] == 50
    assert payload[0]["to_score"] == 80


def test_symbol_signal_detail_endpoint_combines_latest_and_transitions() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/aapl?transition_limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["latest"]["ticker"] == "AAPL"
    assert payload["recent_transitions"][0]["ticker"] == "AAPL"


def test_watchlist_candidates_endpoint_returns_portfolio_lanes() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/watchlist-candidates?limit=3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lanes"][0]["id"] == "bullish_alignment"
    assert payload["lanes"][0]["candidates"][0]["ticker"] == "AA"
    assert payload["lanes"][0]["candidates"][0]["legacy_action"] == "BUY"
    assert payload["lanes"][0]["candidates"][0]["state_labels"]["weekly"] == "green"


def test_daily_calibration_endpoint_returns_model_health_metrics() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/calibration/daily?ticker=aa&top_tickers=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parameter_set_name"] == "dochia_v0_estimated"
    assert payload["accuracy"] == 0.5
    assert payload["confusion"]["green"]["missing"] == 1
    assert payload["top_tickers"][0]["ticker"] == "aa"


def test_symbol_chart_endpoint_returns_overlay_data() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/aa/chart?sessions=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AA"
    assert payload["bars"][0]["daily_channel_high"] == "67.00"
    assert payload["events"][0]["timeframe"] == "daily"


def test_symbol_signal_detail_404_when_no_latest_score() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/missing")

    assert response.status_code == 404
