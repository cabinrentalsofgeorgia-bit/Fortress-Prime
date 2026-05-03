import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.signals import get_signal_store
from app.main import create_app

PARAMETER_SET_ID = UUID("11111111-1111-1111-1111-111111111111")
TRANSITION_ID = UUID("22222222-2222-2222-2222-222222222222")
DECISION_ID = UUID("33333333-3333-3333-3333-333333333333")
ACCEPTANCE_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeSignalStore:
    def latest_scores(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        parameter_set: str | None = None,
    ) -> list[dict[str, Any]]:
        if ticker == "MISSING":
            return []
        parameter_set_name = parameter_set or "dochia_v0_estimated"
        row = {
            "ticker": ticker or "AA",
            "bar_date": dt.date(2026, 4, 24),
            "parameter_set_id": PARAMETER_SET_ID,
            "parameter_set_name": parameter_set_name,
            "dochia_version": "v0.2-candidate" if parameter_set else "v0",
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
        parameter_set: str | None = None,
    ) -> list[dict[str, Any]]:
        parameter_set_name = parameter_set or "dochia_v0_estimated"
        row = {
            "id": TRANSITION_ID,
            "ticker": ticker or "AA",
            "parameter_set_name": parameter_set_name,
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

    def watchlist_candidates(
        self,
        *,
        limit: int,
        parameter_set: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        parameter_set_name = parameter_set or "dochia_v0_estimated"
        row = {
            "ticker": "AA",
            "bar_date": dt.date(2026, 4, 24),
            "parameter_set_name": parameter_set_name,
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
        event_window_days: int = 3,
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
            "exact_event_matches": 1,
            "exact_event_accuracy": 0.5,
            "window_event_matches": 1,
            "window_event_accuracy": 0.5,
            "event_window_days": event_window_days,
            "no_generated_event_observations": 1,
            "opposite_generated_event_observations": 0,
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
            "event_confusion": {
                "green": {"green": 1, "red": 0, "none": 0, "missing": 1},
                "red": {"green": 0, "red": 0, "none": 1, "missing": 0},
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

    def promotion_gate(
        self,
        *,
        candidate_parameter_set: str,
        since: dt.date | None = None,
        until: dt.date | None = None,
        top_tickers: int = 20,
        event_window_days: int = 3,
    ) -> dict[str, Any]:
        production_calibration = self.daily_calibration(
            since=since,
            until=until,
            top_tickers=top_tickers,
            event_window_days=event_window_days,
        )
        candidate_calibration = {
            **self.daily_calibration(
                since=since,
                until=until,
                parameter_set=candidate_parameter_set,
                top_tickers=top_tickers,
                event_window_days=event_window_days,
            ),
            "window_event_accuracy": 0.46,
            "exact_event_accuracy": 0.3,
            "score_mae": 42.0,
        }
        return {
            "generated_at": dt.datetime(2026, 5, 2, 22, 0, tzinfo=dt.UTC),
            "candidate_parameter_set": candidate_parameter_set,
            "baseline_parameter_set": "dochia_v0_estimated",
            "since": since,
            "until": until,
            "event_window_days": event_window_days,
            "production": {
                "id": "production",
                "label": "Production",
                "parameter_set_name": production_calibration["parameter_set_name"],
                "daily_trigger_mode": "close",
                "latest_bar_date": dt.date(2026, 4, 24),
                "signal_count": 120,
                "bullish_count": 40,
                "risk_count": 20,
                "neutral_count": 18,
                "reentry_count": 7,
                "average_score": 12.5,
                "calibration": {
                    "total_observations": production_calibration["total_observations"],
                    "covered_observations": production_calibration["covered_observations"],
                    "accuracy": production_calibration["accuracy"],
                    "exact_event_accuracy": production_calibration["exact_event_accuracy"],
                    "window_event_accuracy": production_calibration["window_event_accuracy"],
                    "coverage_rate": production_calibration["coverage_rate"],
                    "exact_coverage_rate": production_calibration["exact_coverage_rate"],
                    "score_mae": production_calibration["score_mae"],
                    "score_rmse": production_calibration["score_rmse"],
                },
            },
            "candidate": {
                "id": "candidate",
                "label": "v0.2 Range",
                "parameter_set_name": candidate_parameter_set,
                "daily_trigger_mode": "range",
                "latest_bar_date": dt.date(2026, 4, 24),
                "signal_count": 118,
                "bullish_count": 43,
                "risk_count": 21,
                "neutral_count": 15,
                "reentry_count": 9,
                "average_score": 14.0,
                "calibration": {
                    "total_observations": candidate_calibration["total_observations"],
                    "covered_observations": candidate_calibration["covered_observations"],
                    "accuracy": candidate_calibration["accuracy"],
                    "exact_event_accuracy": candidate_calibration["exact_event_accuracy"],
                    "window_event_accuracy": candidate_calibration["window_event_accuracy"],
                    "coverage_rate": candidate_calibration["coverage_rate"],
                    "exact_coverage_rate": candidate_calibration["exact_coverage_rate"],
                    "score_mae": candidate_calibration["score_mae"],
                    "score_rmse": candidate_calibration["score_rmse"],
                },
            },
            "deltas": {
                "window_event_accuracy": 0.0319,
                "exact_event_accuracy": 0.0229,
                "coverage_rate": 0.0,
                "score_mae": -1.94,
                "signal_count": -2,
                "reentry_count": 2,
            },
            "guardrails": [
                {
                    "id": "window_event_accuracy",
                    "label": "Window alert match",
                    "status": "pass",
                    "detail": "Candidate should not materially trail production.",
                }
            ],
            "recommendation": {
                "status": "ready_for_shadow",
                "label": "Ready for shadow",
                "rationale": "Candidate clears the compact promotion gate.",
            },
        }

    def shadow_review(
        self,
        *,
        candidate_parameter_set: str,
        lookback_days: int = 30,
        review_limit: int = 8,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]:
        return {
            "generated_at": dt.datetime(2026, 5, 3, 18, 30, tzinfo=dt.UTC),
            "candidate_parameter_set": candidate_parameter_set,
            "baseline_parameter_set": "dochia_v0_estimated",
            "lookback_days": lookback_days,
            "review_limit": review_limit,
            "promotion_gate": self.promotion_gate(
                candidate_parameter_set=candidate_parameter_set,
                top_tickers=review_limit,
            ),
            "lane_reviews": [
                {
                    "lane_id": "reentry",
                    "label": "Re-entry",
                    "production_tickers": ["AA", "HUT"],
                    "candidate_tickers": ["AA", "BTU"],
                    "added_tickers": ["BTU"],
                    "removed_tickers": ["HUT"],
                    "unchanged_tickers": ["AA"],
                    "churn_rate": 2 / 3,
                }
            ],
            "transition_pressure": [
                {
                    "ticker": "AA",
                    "production_transition_count": 3,
                    "candidate_transition_count": 5,
                    "delta": 2,
                    "latest_candidate_transition_type": "exit_to_reentry",
                    "latest_candidate_transition_date": dt.date(2026, 4, 22),
                }
            ],
            "whipsaw_reviews": [
                {
                    "ticker": "AA",
                    "risk_level": "high",
                    "risk_score": 82,
                    "event_count": 9,
                    "whipsaw_count": 5,
                    "whipsaw_rate": 0.625,
                    "win_rate": 0.55,
                    "average_directional_return": 0.01,
                    "latest_whipsaw_date": dt.date(2026, 4, 23),
                }
            ],
            "checklist": [
                {
                    "id": "promotion_gate",
                    "label": "Promotion Gate",
                    "status": "pass",
                    "detail": "Candidate clears the compact promotion gate.",
                },
                {
                    "id": "decision_record",
                    "label": "Human Decision Record",
                    "status": "blocked",
                    "detail": "A human promote/defer record is required.",
                },
            ],
            "recommendation": {
                "status": "needs_review",
                "label": "Needs human review",
                "rationale": "Evidence is ready, but review pressure remains.",
            },
            "decision_record_template": {
                "candidate_parameter_set": candidate_parameter_set,
                "allowed_decisions": ["defer", "continue_shadow", "promote_to_market_signals"],
                "required_approver": "Financial operator",
                "required_evidence": [
                    "Promotion Gate status",
                    "Lane churn review",
                    "Transition pressure review",
                    "Whipsaw/backtest review",
                    "Rollback criteria",
                ],
            },
        }

    def shadow_review_decision_records(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": DECISION_ID,
                "candidate_parameter_set": candidate_parameter_set or "dochia_v0_2_range_daily",
                "baseline_parameter_set": "dochia_v0_estimated",
                "decision": "continue_shadow",
                "reviewer": "Gary Knight",
                "rationale": "Keep watching lane churn and whipsaw pressure.",
                "rollback_criteria": "Rollback if the promotion gate moves to hold.",
                "reviewed_tickers": ["AA", "BTU"],
                "notes": "Operator reviewed the chart overlays.",
                "shadow_review_generated_at": dt.datetime(2026, 5, 3, 18, 30, tzinfo=dt.UTC),
                "promotion_gate_status": "ready_for_shadow",
                "recommendation_status": "needs_review",
                "created_at": dt.datetime(2026, 5, 3, 19, 0, tzinfo=dt.UTC),
            }
        ][:limit]

    def create_shadow_review_decision_record(
        self,
        *,
        candidate_parameter_set: str,
        decision: str,
        reviewer: str,
        rationale: str,
        rollback_criteria: str,
        reviewed_tickers: list[str],
        notes: str | None = None,
        lookback_days: int = 30,
        review_limit: int = 8,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]:
        return {
            "id": DECISION_ID,
            "candidate_parameter_set": candidate_parameter_set,
            "baseline_parameter_set": "dochia_v0_estimated",
            "decision": decision,
            "reviewer": reviewer,
            "rationale": rationale,
            "rollback_criteria": rollback_criteria,
            "reviewed_tickers": reviewed_tickers,
            "notes": notes,
            "shadow_review_generated_at": dt.datetime(2026, 5, 3, 18, 30, tzinfo=dt.UTC),
            "promotion_gate_status": "ready_for_shadow",
            "recommendation_status": "needs_review",
            "created_at": dt.datetime(2026, 5, 3, 19, 1, tzinfo=dt.UTC),
        }

    def promotion_dry_run(
        self,
        *,
        candidate_parameter_set: str,
        decision_id: str | None = None,
        limit: int = 100,
        min_abs_score: int = 50,
    ) -> dict[str, Any]:
        return {
            "generated_at": dt.datetime(2026, 5, 3, 20, 30, tzinfo=dt.UTC),
            "candidate_parameter_set": candidate_parameter_set,
            "baseline_parameter_set": "dochia_v0_estimated",
            "approval": {
                "status": "ready_for_dry_run",
                "decision_id": DECISION_ID,
                "reviewer": "Gary Knight",
                "decision_created_at": dt.datetime(2026, 5, 3, 19, 1, tzinfo=dt.UTC),
                "rollback_criteria": "Rollback if whipsaw pressure rises.",
                "detail": f"decision_id={decision_id or DECISION_ID}",
            },
            "summary": {
                "target_table": "hedge_fund.market_signals",
                "target_columns": [
                    "ticker",
                    "signal_type",
                    "action",
                    "confidence_score",
                    "price_target",
                    "source_sender",
                    "source_subject",
                    "raw_reasoning",
                    "model_used",
                    "extracted_at",
                ],
                "write_path_enabled": False,
                "candidate_signal_count": 3,
                "proposed_insert_count": min(limit, 2),
                "bullish_count": 1,
                "risk_count": 1,
                "skipped_neutral_count": 1,
                "latest_bar_date": dt.date(2026, 4, 24),
                "min_abs_score": min_abs_score,
            },
            "proposed_rows": [
                {
                    "ticker": "AA",
                    "action": "BUY",
                    "signal_type": "Dochia bullish alignment",
                    "confidence_score": 80,
                    "price_target": None,
                    "source_sender": "Dochia Signal Engine",
                    "source_subject": f"Dry-run promotion {candidate_parameter_set}",
                    "raw_reasoning": "Dochia dry-run signal for AA: composite score +80.",
                    "model_used": "v0.2-candidate",
                    "extracted_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
                    "candidate_bar_date": dt.date(2026, 4, 24),
                    "composite_score": 80,
                    "lineage": {
                        "source_pipeline": "dochia_signal_scores",
                        "parameter_set": candidate_parameter_set,
                        "model_version": "v0.2-candidate",
                        "computed_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
                        "explanation_payload": {
                            "ticker": "AA",
                            "composite_score": 80,
                        },
                        "rollback_marker": "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
                    },
                },
                {
                    "ticker": "AGIO",
                    "action": "SELL",
                    "signal_type": "Dochia risk alignment",
                    "confidence_score": 80,
                    "price_target": None,
                    "source_sender": "Dochia Signal Engine",
                    "source_subject": f"Dry-run promotion {candidate_parameter_set}",
                    "raw_reasoning": "Dochia dry-run signal for AGIO: composite score -80.",
                    "model_used": "v0.2-candidate",
                    "extracted_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
                    "candidate_bar_date": dt.date(2026, 4, 24),
                    "composite_score": -80,
                    "lineage": {
                        "source_pipeline": "dochia_signal_scores",
                        "parameter_set": candidate_parameter_set,
                        "model_version": "v0.2-candidate",
                        "computed_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
                        "explanation_payload": {
                            "ticker": "AGIO",
                            "composite_score": -80,
                        },
                        "rollback_marker": "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
                    },
                },
            ][:limit],
        }

    def promotion_dry_run_acceptances(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_parameter_set": candidate_parameter_set or "dochia_v0_2_range_daily",
                "baseline_parameter_set": "dochia_v0_estimated",
                "accepted_by": "Gary Knight",
                "acceptance_rationale": "Dry-run rows match the reviewed promote decision.",
                "rollback_criteria": "Rollback if whipsaw pressure rises.",
                "dry_run_generated_at": dt.datetime(2026, 5, 3, 20, 30, tzinfo=dt.UTC),
                "dry_run_candidate_signal_count": 3,
                "dry_run_proposed_insert_count": 2,
                "dry_run_bullish_count": 1,
                "dry_run_risk_count": 1,
                "dry_run_skipped_neutral_count": 1,
                "min_abs_score": 50,
                "target_table": "hedge_fund.market_signals",
                "target_columns": [
                    "ticker",
                    "signal_type",
                    "action",
                    "confidence_score",
                    "price_target",
                    "source_sender",
                    "source_subject",
                    "raw_reasoning",
                    "model_used",
                    "extracted_at",
                ],
                "created_at": dt.datetime(2026, 5, 3, 20, 45, tzinfo=dt.UTC),
            }
        ][:limit]

    def create_promotion_dry_run_acceptance(
        self,
        *,
        candidate_parameter_set: str,
        accepted_by: str,
        acceptance_rationale: str,
        decision_id: str | None = None,
        limit: int = 500,
        min_abs_score: int = 50,
    ) -> dict[str, Any]:
        if accepted_by == "Blocked":
            raise ValueError("Cannot accept dry-run output without a ready promote decision record.")
        return {
            **self.promotion_dry_run_acceptances(
                candidate_parameter_set=candidate_parameter_set,
                limit=1,
            )[0],
            "accepted_by": accepted_by,
            "acceptance_rationale": acceptance_rationale,
            "decision_record_id": UUID(decision_id) if decision_id else DECISION_ID,
            "min_abs_score": min_abs_score,
            "dry_run_proposed_insert_count": min(limit, 2),
        }

    def symbol_chart(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "parameter_set_name": parameter_set or "dochia_v0_estimated",
            "daily_trigger_mode": "range" if parameter_set else "close",
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

    def symbol_whipsaw_risk(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "parameter_set_name": parameter_set or "dochia_v0_estimated",
            "daily_trigger_mode": "range" if parameter_set else "close",
            "sessions": sessions,
            "as_of": as_of or dt.date(2026, 4, 24),
            "whipsaw_window_sessions": whipsaw_window_sessions,
            "outcome_horizon_sessions": outcome_horizon_sessions,
            "event_count": 4,
            "whipsaw_count": 2,
            "whipsaw_rate": 2 / 3,
            "latest_whipsaw_date": dt.date(2026, 4, 22),
            "risk_score": 67,
            "risk_level": "elevated",
            "outcome": {
                "horizon_sessions": outcome_horizon_sessions,
                "evaluated_events": 3,
                "win_count": 2,
                "win_rate": 2 / 3,
                "average_directional_return": 0.0123,
                "median_directional_return": 0.01,
                "p25_directional_return": -0.005,
                "p75_directional_return": 0.02,
            },
            "recent_events": [
                {
                    "event_date": dt.date(2026, 4, 22),
                    "state": "green",
                    "sessions_since_previous": 2,
                    "is_whipsaw": True,
                    "directional_return": 0.018,
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


def test_latest_scores_endpoint_accepts_parameter_set_selector() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/latest?limit=1&parameter_set=dochia_v0_2_range_daily"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["parameter_set_name"] == "dochia_v0_2_range_daily"
    assert payload[0]["dochia_version"] == "v0.2-candidate"


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


def test_transitions_endpoint_accepts_parameter_set_selector() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/transitions?limit=1&parameter_set=dochia_v0_2_range_daily"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["parameter_set_name"] == "dochia_v0_2_range_daily"


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


def test_symbol_signal_detail_endpoint_accepts_parameter_set_selector() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/aapl?parameter_set=dochia_v0_2_range_daily")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest"]["parameter_set_name"] == "dochia_v0_2_range_daily"
    assert payload["recent_transitions"][0]["parameter_set_name"] == "dochia_v0_2_range_daily"


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


def test_watchlist_candidates_endpoint_accepts_parameter_set_selector() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/watchlist-candidates?limit=3&parameter_set=dochia_v0_2_range_daily"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lanes"][0]["candidates"][0]["parameter_set_name"] == "dochia_v0_2_range_daily"


def test_daily_calibration_endpoint_returns_model_health_metrics() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/calibration/daily?ticker=aa&top_tickers=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parameter_set_name"] == "dochia_v0_estimated"
    assert payload["accuracy"] == 0.5
    assert payload["exact_event_accuracy"] == 0.5
    assert payload["confusion"]["green"]["missing"] == 1
    assert payload["event_confusion"]["red"]["none"] == 1
    assert payload["top_tickers"][0]["ticker"] == "aa"


def test_promotion_gate_endpoint_compares_candidate_to_production() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-gate/daily"
        "?candidate_parameter_set=dochia_v0_2_range_daily&top_tickers=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_parameter_set"] == "dochia_v0_2_range_daily"
    assert payload["production"]["daily_trigger_mode"] == "close"
    assert payload["candidate"]["daily_trigger_mode"] == "range"
    assert payload["deltas"]["signal_count"] == -2
    assert payload["guardrails"][0]["status"] == "pass"
    assert payload["recommendation"]["status"] == "ready_for_shadow"


def test_shadow_review_endpoint_returns_decision_packet() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/shadow-review/daily"
        "?candidate_parameter_set=dochia_v0_2_range_daily&review_limit=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_parameter_set"] == "dochia_v0_2_range_daily"
    assert payload["recommendation"]["status"] == "needs_review"
    assert payload["lane_reviews"][0]["added_tickers"] == ["BTU"]
    assert payload["transition_pressure"][0]["latest_candidate_transition_type"] == "exit_to_reentry"
    assert payload["whipsaw_reviews"][0]["risk_level"] == "high"
    assert payload["decision_record_template"]["allowed_decisions"][-1] == "promote_to_market_signals"


def test_shadow_review_decision_records_endpoint_returns_audit_rows() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/shadow-review/decision-records"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == str(DECISION_ID)
    assert payload[0]["decision"] == "continue_shadow"
    assert payload[0]["reviewed_tickers"] == ["AA", "BTU"]
    assert payload[0]["recommendation_status"] == "needs_review"


def test_shadow_review_decision_records_endpoint_creates_audit_row() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/shadow-review/decision-records",
        json={
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "decision": "promote_to_market_signals",
            "reviewer": "Gary Knight",
            "rationale": "Promotion gate cleared and reviewed tickers are acceptable.",
            "rollback_criteria": "Rollback if whipsaw pressure rises or the gate moves to hold.",
            "reviewed_tickers": ["aa", "BTU", "AA"],
            "notes": "Proceed to dry-run only.",
            "review_limit": 3,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["candidate_parameter_set"] == "dochia_v0_2_range_daily"
    assert payload["decision"] == "promote_to_market_signals"
    assert payload["reviewer"] == "Gary Knight"
    assert payload["reviewed_tickers"] == ["AA", "BTU"]
    assert payload["promotion_gate_status"] == "ready_for_shadow"


def test_promotion_dry_run_endpoint_returns_read_only_market_signal_plan() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-dry-run/daily"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=2&min_abs_score=50"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_parameter_set"] == "dochia_v0_2_range_daily"
    assert payload["approval"]["status"] == "ready_for_dry_run"
    assert payload["summary"]["target_table"] == "hedge_fund.market_signals"
    assert payload["summary"]["write_path_enabled"] is False
    assert payload["summary"]["proposed_insert_count"] == 2
    assert payload["proposed_rows"][0]["action"] == "BUY"
    assert payload["proposed_rows"][1]["action"] == "SELL"
    assert payload["proposed_rows"][0]["lineage"]["source_pipeline"] == "dochia_signal_scores"
    assert "rollback_marker" in payload["proposed_rows"][0]["lineage"]


def test_promotion_dry_run_acceptances_endpoint_returns_audit_rows() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-dry-run/acceptances"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == str(ACCEPTANCE_ID)
    assert payload[0]["decision_record_id"] == str(DECISION_ID)
    assert payload[0]["dry_run_proposed_insert_count"] == 2
    assert payload[0]["target_table"] == "hedge_fund.market_signals"


def test_promotion_dry_run_acceptances_endpoint_creates_audit_row() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/acceptances",
        json={
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "decision_id": str(DECISION_ID),
            "accepted_by": "Gary Knight",
            "acceptance_rationale": "Dry-run output matches the reviewed promote decision.",
            "limit": 2,
            "min_abs_score": 50,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["accepted_by"] == "Gary Knight"
    assert payload["decision_record_id"] == str(DECISION_ID)
    assert payload["acceptance_rationale"] == "Dry-run output matches the reviewed promote decision."
    assert payload["dry_run_proposed_insert_count"] == 2


def test_promotion_dry_run_acceptances_endpoint_rejects_without_ready_decision() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/acceptances",
        json={
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "accepted_by": "Blocked",
            "acceptance_rationale": "Dry-run output cannot be accepted without approval.",
        },
    )

    assert response.status_code == 400
    assert "ready promote decision" in response.json()["detail"]


def test_symbol_chart_endpoint_returns_overlay_data() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/aa/chart?sessions=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AA"
    assert payload["parameter_set_name"] == "dochia_v0_estimated"
    assert payload["daily_trigger_mode"] == "close"
    assert payload["bars"][0]["daily_channel_high"] == "67.00"
    assert payload["events"][0]["timeframe"] == "daily"


def test_symbol_chart_endpoint_accepts_parameter_set_selector() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/aa/chart?sessions=30&parameter_set=dochia_v0_2_range_daily"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parameter_set_name"] == "dochia_v0_2_range_daily"
    assert payload["daily_trigger_mode"] == "range"


def test_symbol_whipsaw_risk_endpoint_returns_backtest_context() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/aa/whipsaw-risk"
        "?sessions=60&parameter_set=dochia_v0_2_range_daily"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AA"
    assert payload["parameter_set_name"] == "dochia_v0_2_range_daily"
    assert payload["daily_trigger_mode"] == "range"
    assert payload["whipsaw_count"] == 2
    assert payload["risk_level"] == "elevated"
    assert payload["outcome"]["horizon_sessions"] == 5
    assert payload["recent_events"][0]["is_whipsaw"] is True


def test_symbol_signal_detail_404_when_no_latest_score() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get("/api/financial/signals/missing")

    assert response.status_code == 404
