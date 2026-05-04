import datetime as dt
import hashlib
from collections import Counter
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
EXECUTION_ID = UUID("55555555-5555-5555-5555-555555555555")
OPERATOR_MEMBERSHIP_ID = UUID("66666666-6666-6666-6666-666666666666")
OPERATOR_TOKEN = "marketclub-operator-token"
OPERATOR_TOKEN_SHA256 = hashlib.sha256(OPERATOR_TOKEN.encode("utf-8")).hexdigest()


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

    def promotion_dry_run_verification(
        self,
        *,
        candidate_parameter_set: str,
        production_parameter_set: str = "dochia_v0_estimated",
        decision_id: str | None = None,
        limit: int = 500,
        min_abs_score: int = 50,
    ) -> dict[str, Any]:
        checked = min(limit, 2)
        return {
            "generated_at": dt.datetime(2026, 5, 3, 20, 31, tzinfo=dt.UTC),
            "candidate_parameter_set": candidate_parameter_set,
            "production_parameter_set": production_parameter_set,
            "overall_status": "PASS",
            "proposed_rows_checked": checked,
            "passed_rows": checked,
            "failed_rows": 0,
            "inconclusive_rows": 0,
            "cross_model_diagnostic_only_rows": 1,
            "rows": [
                {
                    "row_status": "PASS",
                    "ticker": "ACLX",
                    "candidate_bar_date": dt.date(2026, 4, 24),
                    "candidate_score": 80,
                    "candidate_action": "BUY",
                    "candidate_monthly_triangle": 1,
                    "candidate_weekly_triangle": 1,
                    "candidate_daily_triangle": 1,
                    "latest_candidate_transition_date": dt.date(2026, 4, 23),
                    "latest_candidate_transition_type": "breakout_bullish",
                    "prior_score": 50,
                    "new_score": 80,
                    "production_score": 50,
                    "production_daily_triangle": -1,
                    "conflict_type": "CROSS_MODEL_DIAGNOSTIC_ONLY",
                    "explanation": "Production baseline differs from candidate, but candidate lineage is clean.",
                }
            ][:checked],
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

    def _promotion_execution(
        self,
        *,
        rollback_status: str = "active",
        rollback_by: str | None = None,
        rollback_reason: str | None = None,
        rolled_back_at: dt.datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "id": EXECUTION_ID,
            "acceptance_id": ACCEPTANCE_ID,
            "decision_record_id": DECISION_ID,
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "baseline_parameter_set": "dochia_v0_estimated",
            "operator_membership_id": OPERATOR_MEMBERSHIP_ID,
            "executed_by": "MarketClub Operator",
            "execution_rationale": "Operator accepted the verified dry-run output.",
            "idempotency_key": f"acceptance:{ACCEPTANCE_ID}",
            "dry_run_generated_at": dt.datetime(2026, 5, 3, 20, 30, tzinfo=dt.UTC),
            "dry_run_proposed_insert_count": 2,
            "verification_status": "PASS",
            "inserted_market_signal_ids": [1201, 1202],
            "rollback_markers": [
                "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
                "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
            ],
            "rollback_status": rollback_status,
            "rollback_operator_membership_id": OPERATOR_MEMBERSHIP_ID if rollback_by else None,
            "rollback_by": rollback_by,
            "rollback_reason": rollback_reason,
            "rolled_back_at": rolled_back_at,
            "created_at": dt.datetime(2026, 5, 3, 21, 0, tzinfo=dt.UTC),
        }

    def _promotion_rollback_drill(
        self,
        *,
        rollback_status: str = "active",
        rollback_by: str | None = None,
        rolled_back_at: dt.datetime | None = None,
    ) -> dict[str, Any]:
        already_rolled_back = rollback_status == "rolled_back"
        return {
            "execution_id": EXECUTION_ID,
            "dry_run_acceptance_id": ACCEPTANCE_ID,
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "baseline_parameter_set": "dochia_v0_estimated",
            "executed_by": "MarketClub Operator",
            "executed_at": dt.datetime(2026, 5, 3, 21, 0, tzinfo=dt.UTC),
            "inserted_market_signal_ids": [1201, 1202],
            "rollback_markers": [
                "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
                "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
            ],
            "audited_market_signal_ids": [1201, 1202],
            "rollback_preview_market_signal_ids": [] if already_rolled_back else [1201, 1202],
            "rollback_preview_count": 0 if already_rolled_back else 2,
            "rollback_eligibility": "ALREADY_ROLLED_BACK" if already_rolled_back else "ELIGIBLE",
            "rollback_eligible": not already_rolled_back,
            "already_rolled_back": already_rolled_back,
            "rollback_status": rollback_status,
            "rollback_by": rollback_by,
            "rollback_attempted_at": rolled_back_at,
            "rolled_back_at": rolled_back_at,
        }

    def promotion_executions(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [self._promotion_execution()][:limit]

    def promotion_rollback_drills(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [
            self._promotion_rollback_drill(),
            self._promotion_rollback_drill(
                rollback_status="rolled_back",
                rollback_by="MarketClub Operator",
                rolled_back_at=dt.datetime(2026, 5, 3, 21, 30, tzinfo=dt.UTC),
            ),
        ][:limit]

    def promotion_lifecycle_timeline(
        self,
        *,
        promotion_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            {
                "ts": dt.datetime(2026, 5, 3, 19, 0, tzinfo=dt.UTC),
                "type": "DECISION_CREATED",
                "decision_id": DECISION_ID,
                "acceptance_id": None,
                "execution_id": None,
                "candidate_id": "dochia_v0_2_range_daily",
                "actor": "Gary Knight",
                "meta": {
                    "rationale": "Keep watching lane churn and whipsaw pressure.",
                    "risk_flags": ["churn", "whipsaw"],
                },
            },
            {
                "ts": dt.datetime(2026, 5, 3, 20, 45, tzinfo=dt.UTC),
                "type": "ACCEPTANCE_CREATED",
                "decision_id": DECISION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "execution_id": None,
                "candidate_id": "dochia_v0_2_range_daily",
                "actor": "Gary Knight",
                "meta": {"proposed_rows": 2},
            },
            {
                "ts": dt.datetime(2026, 5, 3, 21, 0, tzinfo=dt.UTC),
                "type": "EXECUTION_COMPLETED",
                "decision_id": DECISION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "execution_id": EXECUTION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "actor": "MarketClub Operator",
                "meta": {"inserted_count": 2, "idempotency_key": f"acceptance:{ACCEPTANCE_ID}"},
            },
            {
                "ts": dt.datetime(2026, 5, 3, 21, 30, tzinfo=dt.UTC),
                "type": "ROLLBACK_COMPLETED",
                "decision_id": DECISION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "execution_id": EXECUTION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "actor": "MarketClub Operator",
                "meta": {"removed_count": 2},
            },
        ][:limit]

    def promotion_reconciliation(
        self,
        *,
        promotion_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [
            {
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "status": "HEALTHY",
                "checks": {
                    "decision_link": "PASS",
                    "verification_gate": "PASS",
                    "execution_count_match": "PASS",
                    "write_integrity": "PASS",
                    "extraneous_writes": "PASS",
                    "rollback_integrity": "NA",
                    "idempotency": "PASS",
                },
                "warnings": {
                    "cross_model_diagnostic_only": 0,
                    "high_churn_flag": False,
                    "whipsaw_flag": False,
                },
                "drilldown": {
                    "audited_market_signal_ids": [1201, 1202],
                    "live_audited_market_signal_ids": [1201, 1202],
                    "removed_market_signal_ids": [],
                    "removed_ids_hash": None,
                },
                "explanation": "Promotion audit is healthy across audited invariants.",
            }
        ][:limit]

    def promotion_post_execution_monitoring(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        rows = [
            {
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "baseline_parameter_set": "dochia_v0_estimated",
                "executed_by": "MarketClub Operator",
                "executed_at": dt.datetime(2026, 5, 3, 21, 0, tzinfo=dt.UTC),
                "rollback_status": "active",
                "market_signal_id": 1201,
                "market_signal_live": True,
                "ticker": "AA",
                "action": "BUY",
                "confidence_score": 80,
                "candidate_bar_date": dt.date(2026, 4, 24),
                "rollback_marker": "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
                "candidate_score": 80,
                "candidate_monthly_triangle": 1,
                "candidate_weekly_triangle": 1,
                "candidate_daily_triangle": 1,
                "entry_close": Decimal("69.00"),
                "outcome_1d_bar_date": dt.date(2026, 4, 27),
                "outcome_1d_close": Decimal("70.00"),
                "outcome_1d_directional_return": Decimal("0.014493"),
                "outcome_5d_bar_date": dt.date(2026, 5, 1),
                "outcome_5d_close": Decimal("66.00"),
                "outcome_5d_directional_return": Decimal("-0.043478"),
                "outcome_20d_bar_date": None,
                "outcome_20d_close": None,
                "outcome_20d_directional_return": None,
                "latest_candidate_bar_date": dt.date(2026, 5, 1),
                "latest_candidate_score": 20,
                "latest_monthly_triangle": 1,
                "latest_weekly_triangle": 1,
                "latest_daily_triangle": -1,
                "score_delta": -60,
                "signal_decay_flag": True,
                "signal_decay_date": dt.date(2026, 4, 30),
                "signal_decay_score": 20,
                "signal_decay_daily_triangle": -1,
                "whipsaw_after_promotion_flag": True,
                "whipsaw_transition_date": dt.date(2026, 4, 30),
                "whipsaw_transition_type": "breakout_bearish",
                "whipsaw_to_score": -50,
                "drift_status": "PRICE_AND_SCORE_DRIFT",
                "rollback_recommendation": "REVIEW_ROLLBACK_WARNING",
                "monitoring_status": "WARNING",
                "explanation": "Candidate state whipsawed after promotion; warning only.",
            },
            {
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "baseline_parameter_set": "dochia_v0_estimated",
                "executed_by": "MarketClub Operator",
                "executed_at": dt.datetime(2026, 5, 3, 21, 0, tzinfo=dt.UTC),
                "rollback_status": "active",
                "market_signal_id": 1202,
                "market_signal_live": True,
                "ticker": "AGIO",
                "action": "BUY",
                "confidence_score": 80,
                "candidate_bar_date": dt.date(2026, 4, 24),
                "rollback_marker": "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
                "candidate_score": 80,
                "candidate_monthly_triangle": 1,
                "candidate_weekly_triangle": 1,
                "candidate_daily_triangle": 1,
                "entry_close": Decimal("32.00"),
                "outcome_1d_bar_date": dt.date(2026, 4, 27),
                "outcome_1d_close": Decimal("32.50"),
                "outcome_1d_directional_return": Decimal("0.015625"),
                "outcome_5d_bar_date": None,
                "outcome_5d_close": None,
                "outcome_5d_directional_return": None,
                "outcome_20d_bar_date": None,
                "outcome_20d_close": None,
                "outcome_20d_directional_return": None,
                "latest_candidate_bar_date": dt.date(2026, 4, 27),
                "latest_candidate_score": 80,
                "latest_monthly_triangle": 1,
                "latest_weekly_triangle": 1,
                "latest_daily_triangle": 1,
                "score_delta": 0,
                "signal_decay_flag": False,
                "signal_decay_date": None,
                "signal_decay_score": None,
                "signal_decay_daily_triangle": None,
                "whipsaw_after_promotion_flag": False,
                "whipsaw_transition_date": None,
                "whipsaw_transition_type": None,
                "whipsaw_to_score": None,
                "drift_status": "PENDING",
                "rollback_recommendation": "NO_WARNING",
                "monitoring_status": "PENDING",
                "explanation": "Outcome windows are still pending.",
            },
        ][:limit]
        return {
            "generated_at": dt.datetime(2026, 5, 4, 13, 0, tzinfo=dt.UTC),
            "promotion_id": promotion_id,
            "summary": {
                "rows_checked": len(rows),
                "live_rows": sum(1 for row in rows if row["market_signal_live"]),
                "pending_rows": sum(1 for row in rows if row["monitoring_status"] == "PENDING"),
                "healthy_rows": sum(1 for row in rows if row["monitoring_status"] == "HEALTHY"),
                "warning_rows": sum(1 for row in rows if row["monitoring_status"] == "WARNING"),
                "rollback_warning_rows": sum(
                    1 for row in rows if row["rollback_recommendation"] == "REVIEW_ROLLBACK_WARNING"
                ),
                "whipsaw_after_promotion_rows": sum(
                    1 for row in rows if row["whipsaw_after_promotion_flag"]
                ),
                "signal_decay_rows": sum(1 for row in rows if row["signal_decay_flag"]),
                "adverse_5d_rows": sum(
                    1
                    for row in rows
                    if row["outcome_5d_directional_return"] is not None
                    and row["outcome_5d_directional_return"] < 0
                ),
                "adverse_20d_rows": 0,
            },
            "rows": rows,
        }

    def promotion_post_execution_alerts(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        alerts = [
            {
                "alert_id": "signal-decay-aa",
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "market_signal_id": 1201,
                "ticker": "AA",
                "action": "BUY",
                "candidate_bar_date": dt.date(2026, 4, 24),
                "alert_type": "SIGNAL_DECAY",
                "severity": "HIGH",
                "alert_status": "ACTIVE",
                "alert_date": dt.date(2026, 4, 30),
                "metric_value": Decimal("20"),
                "rollback_recommendation": "REVIEW_ROLLBACK_WARNING",
                "monitoring_status": "WARNING",
                "drift_status": "PRICE_AND_SCORE_DRIFT",
                "evidence": {"signal_decay_score": 20, "score_delta": -60},
                "explanation": "Candidate score or daily triangle decayed after promotion.",
                "operator_guidance": (
                    "Warning only: review the audited execution; no automated rollback is performed."
                ),
            },
            {
                "alert_id": "whipsaw-aa",
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "market_signal_id": 1201,
                "ticker": "AA",
                "action": "BUY",
                "candidate_bar_date": dt.date(2026, 4, 24),
                "alert_type": "WHIPSAW_AFTER_PROMOTION",
                "severity": "HIGH",
                "alert_status": "ACTIVE",
                "alert_date": dt.date(2026, 4, 30),
                "metric_value": Decimal("-50"),
                "rollback_recommendation": "REVIEW_ROLLBACK_WARNING",
                "monitoring_status": "WARNING",
                "drift_status": "PRICE_AND_SCORE_DRIFT",
                "evidence": {"whipsaw_transition_type": "breakout_bearish"},
                "explanation": "Candidate produced an opposite transition after promotion.",
                "operator_guidance": (
                    "Warning only: review whipsaw context; no automatic trade or signal change is made."
                ),
            },
            {
                "alert_id": "drift-aa",
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "market_signal_id": 1201,
                "ticker": "AA",
                "action": "BUY",
                "candidate_bar_date": dt.date(2026, 4, 24),
                "alert_type": "DRIFT",
                "severity": "HIGH",
                "alert_status": "ACTIVE",
                "alert_date": dt.date(2026, 5, 1),
                "metric_value": Decimal("-0.043478"),
                "rollback_recommendation": "REVIEW_ROLLBACK_WARNING",
                "monitoring_status": "WARNING",
                "drift_status": "PRICE_AND_SCORE_DRIFT",
                "evidence": {"outcome_5d_directional_return": "-0.043478"},
                "explanation": "Promoted signal drifted away from candidate expectation.",
                "operator_guidance": (
                    "Warning only: review candidate drift; no automatic trade or signal change is made."
                ),
            },
            {
                "alert_id": "stale-agio",
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "market_signal_id": 1202,
                "ticker": "AGIO",
                "action": "BUY",
                "candidate_bar_date": dt.date(2026, 4, 24),
                "alert_type": "STALE_EXECUTION_MONITORING",
                "severity": "MEDIUM",
                "alert_status": "ACTIVE",
                "alert_date": dt.date(2026, 5, 3),
                "metric_value": Decimal("2.5"),
                "rollback_recommendation": "NO_WARNING",
                "monitoring_status": "PENDING",
                "drift_status": "PENDING",
                "evidence": {"outcome_1d_bar_date": None},
                "explanation": "Execution monitoring is stale.",
                "operator_guidance": (
                    "Warning only: verify data freshness; no automatic trade, signal, "
                    "or rollback action is made."
                ),
            },
            {
                "alert_id": "rollback-review-aa",
                "execution_id": EXECUTION_ID,
                "acceptance_id": ACCEPTANCE_ID,
                "decision_record_id": DECISION_ID,
                "candidate_id": "dochia_v0_2_range_daily",
                "market_signal_id": 1201,
                "ticker": "AA",
                "action": "BUY",
                "candidate_bar_date": dt.date(2026, 4, 24),
                "alert_type": "ROLLBACK_RECOMMENDATION",
                "severity": "HIGH",
                "alert_status": "ACTIVE",
                "alert_date": dt.date(2026, 4, 30),
                "metric_value": Decimal("-0.043478"),
                "rollback_recommendation": "REVIEW_ROLLBACK_WARNING",
                "monitoring_status": "WARNING",
                "drift_status": "PRICE_AND_SCORE_DRIFT",
                "evidence": {"rollback_recommendation": "REVIEW_ROLLBACK_WARNING"},
                "explanation": "Monitoring recommends operator rollback review.",
                "operator_guidance": (
                    "Warning only: this alert never calls rollback_guarded_signal_promotion."
                ),
            },
        ][:limit]
        for alert in alerts:
            alert.update(
                {
                    "acknowledgement_count": 0,
                    "acknowledged": False,
                    "latest_acknowledgement_status": None,
                    "latest_acknowledged_by": None,
                    "latest_acknowledged_at": None,
                    "latest_acknowledgement_note": None,
                    "acknowledgement_required": alert["severity"] in {"HIGH", "MEDIUM"},
                }
            )
        if alerts:
            alerts[0].update(
                {
                    "acknowledgement_count": 1,
                    "acknowledged": True,
                    "latest_acknowledgement_status": "WATCHING",
                    "latest_acknowledged_by": "MarketClub Operator",
                    "latest_acknowledged_at": dt.datetime(2026, 5, 4, 13, 45, tzinfo=dt.UTC),
                    "latest_acknowledgement_note": "Operator reviewed decay context.",
                    "acknowledgement_required": False,
                }
            )
        alert_counts = Counter(alert["alert_type"] for alert in alerts)
        severity_counts = Counter(alert["severity"] for alert in alerts)
        return {
            "generated_at": dt.datetime(2026, 5, 4, 13, 30, tzinfo=dt.UTC),
            "promotion_id": promotion_id,
            "summary": {
                "total_alerts": len(alerts),
                "high_alerts": severity_counts["HIGH"],
                "medium_alerts": severity_counts["MEDIUM"],
                "low_alerts": severity_counts["LOW"],
                "signal_decay_alerts": alert_counts["SIGNAL_DECAY"],
                "whipsaw_after_promotion_alerts": alert_counts["WHIPSAW_AFTER_PROMOTION"],
                "drift_alerts": alert_counts["DRIFT"],
                "stale_execution_monitoring_alerts": alert_counts[
                    "STALE_EXECUTION_MONITORING"
                ],
                "rollback_recommendation_alerts": alert_counts["ROLLBACK_RECOMMENDATION"],
            },
            "alerts": alerts,
        }

    def acknowledge_promotion_post_execution_alert(
        self,
        *,
        alert_id: str,
        operator_token_sha256: str,
        acknowledgement_note: str,
        acknowledgement_status: str = "ACKNOWLEDGED",
    ) -> dict[str, Any]:
        if operator_token_sha256 != OPERATOR_TOKEN_SHA256:
            raise ValueError("Active signal operator membership is required for alert acknowledgement")
        alerts = self.promotion_post_execution_alerts(
            promotion_id=str(EXECUTION_ID),
            limit=10,
        )["alerts"]
        alert = next((item for item in alerts if item["alert_id"] == alert_id), None)
        if alert is None:
            raise ValueError("No active post-execution alert found for alert_id")
        return {
            "id": UUID("88888888-8888-8888-8888-888888888888"),
            "alert_id": alert["alert_id"],
            "execution_id": alert["execution_id"],
            "acceptance_id": alert["acceptance_id"],
            "decision_record_id": alert["decision_record_id"],
            "market_signal_id": alert["market_signal_id"],
            "ticker": alert["ticker"],
            "action": alert["action"],
            "candidate_bar_date": alert["candidate_bar_date"],
            "alert_type": alert["alert_type"],
            "severity": alert["severity"],
            "operator_membership_id": OPERATOR_MEMBERSHIP_ID,
            "acknowledged_by": "MarketClub Operator",
            "acknowledgement_status": acknowledgement_status,
            "acknowledgement_note": acknowledgement_note,
            "alert_evidence_snapshot": alert,
            "created_at": dt.datetime(2026, 5, 4, 13, 46, tzinfo=dt.UTC),
        }

    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if operator_token_sha256 != OPERATOR_TOKEN_SHA256:
            raise ValueError("Promotion verification gate blocked execution: FAIL")
        return {
            **self._promotion_execution(),
            "acceptance_id": UUID(acceptance_id),
            "execution_rationale": execution_rationale,
            "idempotency_key": idempotency_key or f"acceptance:{acceptance_id}",
        }

    def rollback_promotion_execution(
        self,
        *,
        execution_id: str,
        operator_token_sha256: str,
        rollback_reason: str,
    ) -> dict[str, Any]:
        if operator_token_sha256 != OPERATOR_TOKEN_SHA256:
            raise ValueError("Active signal admin membership is required")
        if UUID(execution_id) != EXECUTION_ID:
            raise ValueError("No guarded promotion execution found for rollback")
        return self._promotion_execution(
            rollback_status="rolled_back",
            rollback_by="MarketClub Operator",
            rollback_reason=rollback_reason,
            rolled_back_at=dt.datetime(2026, 5, 3, 21, 30, tzinfo=dt.UTC),
        ) | {"id": UUID(execution_id)}

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


class NoAcceptanceSignalStore(FakeSignalStore):
    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raise ValueError("No dry-run acceptance exists for guarded promotion execution")


class NoDecisionSignalStore(FakeSignalStore):
    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raise ValueError("Human promote_to_market_signals decision is required before execution")


class ConflictingExecutionKeySignalStore(FakeSignalStore):
    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key == "operator-accepted-dry-run-20260505":
            raise ValueError("Dry-run acceptance has already been executed")
        return super().execute_guarded_promotion(
            acceptance_id=acceptance_id,
            operator_token_sha256=operator_token_sha256,
            execution_rationale=execution_rationale,
            idempotency_key=idempotency_key,
        )


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


def test_promotion_dry_run_verification_endpoint_returns_gate_summary() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-dry-run/verification"
        "?candidate_parameter_set=dochia_v0_2_range_daily"
        "&production_parameter_set=dochia_v0_estimated"
        "&limit=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "PASS"
    assert payload["proposed_rows_checked"] == 2
    assert payload["cross_model_diagnostic_only_rows"] == 1
    assert payload["rows"][0]["ticker"] == "ACLX"
    assert payload["rows"][0]["conflict_type"] == "CROSS_MODEL_DIAGNOSTIC_ONLY"


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


def test_promotion_executions_endpoint_returns_audit_rows() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-dry-run/executions"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == str(EXECUTION_ID)
    assert payload[0]["acceptance_id"] == str(ACCEPTANCE_ID)
    assert payload[0]["verification_status"] == "PASS"
    assert payload[0]["inserted_market_signal_ids"] == [1201, 1202]
    assert payload[0]["rollback_status"] == "active"


def test_promotion_rollback_drill_endpoint_returns_read_only_scope() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        "/api/financial/signals/promotion-dry-run/executions/rollback-drill"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["execution_id"] == str(EXECUTION_ID)
    assert payload[0]["dry_run_acceptance_id"] == str(ACCEPTANCE_ID)
    assert payload[0]["inserted_market_signal_ids"] == [1201, 1202]
    assert payload[0]["rollback_markers"][0].startswith("dochia-dry-run:")
    assert payload[0]["rollback_eligibility"] == "ELIGIBLE"
    assert payload[0]["rollback_eligible"] is True
    assert payload[0]["rollback_preview_count"] == 2
    assert payload[0]["already_rolled_back"] is False
    assert payload[0]["rollback_attempted_at"] is None
    assert payload[1]["rollback_eligibility"] == "ALREADY_ROLLED_BACK"
    assert payload[1]["rollback_eligible"] is False
    assert payload[1]["already_rolled_back"] is True
    assert payload[1]["rolled_back_at"] == "2026-05-03T21:30:00Z"


def test_promotion_lifecycle_timeline_endpoint_returns_audited_events() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        f"/api/financial/signals/promotion/{EXECUTION_ID}/timeline?limit=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [event["type"] for event in payload] == [
        "DECISION_CREATED",
        "ACCEPTANCE_CREATED",
        "EXECUTION_COMPLETED",
        "ROLLBACK_COMPLETED",
    ]
    assert payload[2]["execution_id"] == str(EXECUTION_ID)
    assert payload[2]["meta"]["inserted_count"] == 2
    assert payload[3]["meta"]["removed_count"] == 2


def test_promotion_reconciliation_endpoint_returns_invariant_checks() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        f"/api/financial/signals/promotion/{EXECUTION_ID}/reconciliation?limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["status"] == "HEALTHY"
    assert payload[0]["checks"]["decision_link"] == "PASS"
    assert payload[0]["checks"]["verification_gate"] == "PASS"
    assert payload[0]["checks"]["idempotency"] == "PASS"
    assert payload[0]["drilldown"]["audited_market_signal_ids"] == [1201, 1202]


def test_promotion_post_execution_monitoring_endpoint_returns_warning_only_tracking() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        f"/api/financial/signals/promotion/{EXECUTION_ID}/monitoring?limit=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["promotion_id"] == str(EXECUTION_ID)
    assert payload["summary"]["rows_checked"] == 2
    assert payload["summary"]["warning_rows"] == 1
    assert payload["summary"]["rollback_warning_rows"] == 1
    assert payload["summary"]["whipsaw_after_promotion_rows"] == 1
    assert payload["summary"]["signal_decay_rows"] == 1
    warning = payload["rows"][0]
    assert warning["ticker"] == "AA"
    assert warning["outcome_1d_directional_return"] == "0.014493"
    assert warning["outcome_5d_directional_return"] == "-0.043478"
    assert warning["outcome_20d_directional_return"] is None
    assert warning["whipsaw_after_promotion_flag"] is True
    assert warning["signal_decay_flag"] is True
    assert warning["drift_status"] == "PRICE_AND_SCORE_DRIFT"
    assert warning["rollback_recommendation"] == "REVIEW_ROLLBACK_WARNING"
    assert "warning" in warning["explanation"].lower()


def test_promotion_post_execution_alerts_endpoint_returns_warning_only_alerts() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.get(
        f"/api/financial/signals/promotion/{EXECUTION_ID}/alerts?limit=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["promotion_id"] == str(EXECUTION_ID)
    assert payload["summary"]["total_alerts"] == 5
    assert payload["summary"]["high_alerts"] == 4
    assert payload["summary"]["medium_alerts"] == 1
    assert payload["summary"]["signal_decay_alerts"] == 1
    assert payload["summary"]["whipsaw_after_promotion_alerts"] == 1
    assert payload["summary"]["drift_alerts"] == 1
    assert payload["summary"]["stale_execution_monitoring_alerts"] == 1
    assert payload["summary"]["rollback_recommendation_alerts"] == 1
    alert_types = {alert["alert_type"] for alert in payload["alerts"]}
    assert alert_types == {
        "SIGNAL_DECAY",
        "WHIPSAW_AFTER_PROMOTION",
        "DRIFT",
        "STALE_EXECUTION_MONITORING",
        "ROLLBACK_RECOMMENDATION",
    }
    assert all(alert["alert_status"] == "ACTIVE" for alert in payload["alerts"])
    assert all("Warning only" in alert["operator_guidance"] for alert in payload["alerts"])
    assert payload["alerts"][0]["acknowledged"] is True
    assert payload["alerts"][0]["latest_acknowledgement_status"] == "WATCHING"
    assert payload["alerts"][1]["acknowledgement_required"] is True
    guidance = " ".join(alert["operator_guidance"] for alert in payload["alerts"])
    assert "no automated rollback is performed" in guidance
    assert "no automatic trade or signal change is made" in guidance
    assert "no automatic trade, signal, or rollback action is made" in guidance


def test_promotion_post_execution_alert_acknowledgement_endpoint_creates_audit_row() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-alerts/whipsaw-aa/acknowledgements",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acknowledgement_status": "WATCHING",
            "acknowledgement_note": "Operator reviewed whipsaw context.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["alert_id"] == "whipsaw-aa"
    assert payload["execution_id"] == str(EXECUTION_ID)
    assert payload["operator_membership_id"] == str(OPERATOR_MEMBERSHIP_ID)
    assert payload["acknowledged_by"] == "MarketClub Operator"
    assert payload["acknowledgement_status"] == "WATCHING"
    assert payload["acknowledgement_note"] == "Operator reviewed whipsaw context."
    assert payload["alert_evidence_snapshot"]["market_signal_id"] == 1201


def test_promotion_post_execution_alert_acknowledgement_rejects_unauthorized_operator() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-alerts/whipsaw-aa/acknowledgements",
        headers={"X-MarketClub-Operator-Token": "bad-marketclub-token"},
        json={
            "acknowledgement_status": "ACKNOWLEDGED",
            "acknowledgement_note": "Operator reviewed whipsaw context.",
        },
    )

    assert response.status_code == 400
    assert "Active signal operator membership is required" in response.json()["detail"]


def test_promotion_post_execution_alert_acknowledgement_rejects_nonexistent_alert() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-alerts/not-real/acknowledgements",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acknowledgement_status": "ACKNOWLEDGED",
            "acknowledgement_note": "Operator reviewed whipsaw context.",
        },
    )

    assert response.status_code == 400
    assert "No active post-execution alert found for alert_id" in response.json()["detail"]


def test_execute_guarded_promotion_endpoint_returns_execution_record() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator accepted the verified dry-run output.",
            "idempotency_key": "operator-accepted-dry-run-20260504",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["acceptance_id"] == str(ACCEPTANCE_ID)
    assert payload["operator_membership_id"] == str(OPERATOR_MEMBERSHIP_ID)
    assert payload["executed_by"] == "MarketClub Operator"
    assert payload["idempotency_key"] == "operator-accepted-dry-run-20260504"
    assert payload["verification_status"] == "PASS"
    assert payload["rollback_markers"][0].startswith("dochia-dry-run:")


def test_execute_guarded_promotion_endpoint_rejects_without_acceptance() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = NoAcceptanceSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": "77777777-7777-7777-7777-777777777777",
            "execution_rationale": "Operator attempted execution without acceptance.",
            "idempotency_key": "operator-no-acceptance-20260504",
        },
    )

    assert response.status_code == 400
    assert "No dry-run acceptance exists" in response.json()["detail"]


def test_execute_guarded_promotion_endpoint_rejects_without_human_decision() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = NoDecisionSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator attempted execution without promote decision.",
            "idempotency_key": "operator-no-decision-20260504",
        },
    )

    assert response.status_code == 400
    assert "Human promote_to_market_signals decision is required" in response.json()["detail"]


def test_execute_guarded_promotion_endpoint_is_idempotent_for_same_key() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)
    payload = {
        "acceptance_id": str(ACCEPTANCE_ID),
        "execution_rationale": "Operator accepted the verified dry-run output.",
        "idempotency_key": "operator-accepted-dry-run-20260504",
    }

    first = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json=payload,
    )
    second = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["inserted_market_signal_ids"] == first.json()["inserted_market_signal_ids"]


def test_execute_guarded_promotion_endpoint_rejects_conflicting_key_after_execution() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = ConflictingExecutionKeySignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator attempted duplicate execution with another key.",
            "idempotency_key": "operator-accepted-dry-run-20260505",
        },
    )

    assert response.status_code == 400
    assert "already been executed" in response.json()["detail"]


def test_execute_guarded_promotion_endpoint_refuses_ticker_date_payload() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator attempted execution with ticker date scope.",
            "idempotency_key": "operator-ticker-date-20260504",
            "ticker": "AA",
            "candidate_bar_date": "2026-04-24",
        },
    )

    assert response.status_code == 422


def test_execute_guarded_promotion_endpoint_links_audit_and_rollback_eligibility() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    execution = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator accepted the verified dry-run output.",
            "idempotency_key": "operator-accepted-dry-run-20260504",
        },
    )
    rollback_drill = client.get(
        "/api/financial/signals/promotion-dry-run/executions/rollback-drill"
        "?candidate_parameter_set=dochia_v0_2_range_daily&limit=1"
    )

    assert execution.status_code == 201
    assert rollback_drill.status_code == 200
    assert execution.json()["inserted_market_signal_ids"] == [1201, 1202]
    assert rollback_drill.json()[0]["dry_run_acceptance_id"] == str(ACCEPTANCE_ID)
    assert rollback_drill.json()[0]["rollback_eligible"] is True


def test_execute_guarded_promotion_endpoint_requires_operator_token() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator attempted execution without authentication.",
        },
    )

    assert response.status_code == 422


def test_execute_guarded_promotion_endpoint_rejects_spoofed_operator_body() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "executed_by": "Spoofed Operator",
            "execution_rationale": "Operator attempted execution with spoofed body.",
        },
    )

    assert response.status_code == 422


def test_execute_guarded_promotion_endpoint_rejects_failed_gate() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions",
        headers={"X-MarketClub-Operator-Token": "wrong-operator-token"},
        json={
            "acceptance_id": str(ACCEPTANCE_ID),
            "execution_rationale": "Operator attempted execution after verification failed.",
        },
    )

    assert response.status_code == 400
    assert "verification gate blocked execution" in response.json()["detail"]


def test_rollback_promotion_execution_endpoint_returns_rolled_back_record() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        f"/api/financial/signals/promotion-dry-run/executions/{EXECUTION_ID}/rollback",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "rollback_reason": "Operator rollback after post-promotion review.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(EXECUTION_ID)
    assert payload["rollback_status"] == "rolled_back"
    assert payload["rollback_operator_membership_id"] == str(OPERATOR_MEMBERSHIP_ID)
    assert payload["rollback_by"] == "MarketClub Operator"
    assert payload["rollback_reason"] == "Operator rollback after post-promotion review."


def test_rollback_promotion_execution_endpoint_is_repeat_safe() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    url = f"/api/financial/signals/promotion-dry-run/executions/{EXECUTION_ID}/rollback"
    body = {"rollback_reason": "Operator repeated rollback after post-promotion review."}

    first = client.post(url, headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN}, json=body)
    second = client.post(url, headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN}, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == str(EXECUTION_ID)
    assert second.json()["rollback_status"] == "rolled_back"


def test_rollback_promotion_execution_endpoint_rejects_unauthorized_operator() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        f"/api/financial/signals/promotion-dry-run/executions/{EXECUTION_ID}/rollback",
        headers={"X-MarketClub-Operator-Token": "wrong-operator-token"},
        json={"rollback_reason": "Operator rollback after post-promotion review."},
    )

    assert response.status_code == 400
    assert "Active signal admin membership is required" in response.json()["detail"]


def test_rollback_promotion_execution_endpoint_rejects_nonexistent_execution() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        "/api/financial/signals/promotion-dry-run/executions/"
        "77777777-7777-7777-7777-777777777777/rollback",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={"rollback_reason": "Operator rollback after post-promotion review."},
    )

    assert response.status_code == 400
    assert "No guarded promotion execution found for rollback" in response.json()["detail"]


def test_rollback_promotion_execution_endpoint_refuses_ticker_date_payload() -> None:
    app = create_app()
    app.dependency_overrides[get_signal_store] = FakeSignalStore
    client = TestClient(app)

    response = client.post(
        f"/api/financial/signals/promotion-dry-run/executions/{EXECUTION_ID}/rollback",
        headers={"X-MarketClub-Operator-Token": OPERATOR_TOKEN},
        json={
            "rollback_reason": "Operator rollback after post-promotion review.",
            "ticker": "AA",
            "candidate_bar_date": "2026-04-24",
        },
    )

    assert response.status_code == 422


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
