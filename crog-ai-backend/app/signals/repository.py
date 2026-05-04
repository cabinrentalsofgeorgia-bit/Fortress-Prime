"""Read models for MarketClub / Dochia app-facing signal endpoints."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from decimal import Decimal
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database import connect
from app.signals.calibration_repository import fetch_daily_calibration
from app.signals.chart_repository import (
    PRODUCTION_PARAMETER_SET,
    daily_trigger_mode_for_parameter_set,
    fetch_symbol_chart,
)
from app.signals.whipsaw_risk import fetch_symbol_whipsaw_risk


class SignalDataStore(Protocol):
    def latest_scores(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        parameter_set: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def recent_transitions(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        transition_type: str | None = None,
        since: dt.date | None = None,
        lookback_days: int | None = None,
        parameter_set: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def watchlist_candidates(
        self,
        *,
        limit: int,
        parameter_set: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]: ...

    def daily_calibration(
        self,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
        ticker: str | None = None,
        parameter_set: str | None = None,
        top_tickers: int = 20,
        event_window_days: int = 3,
    ) -> dict[str, Any]: ...

    def promotion_gate(
        self,
        *,
        candidate_parameter_set: str,
        since: dt.date | None = None,
        until: dt.date | None = None,
        top_tickers: int = 20,
        event_window_days: int = 3,
    ) -> dict[str, Any]: ...

    def shadow_review(
        self,
        *,
        candidate_parameter_set: str,
        lookback_days: int = 30,
        review_limit: int = 8,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]: ...

    def shadow_review_decision_records(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

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
    ) -> dict[str, Any]: ...

    def promotion_dry_run(
        self,
        *,
        candidate_parameter_set: str,
        decision_id: str | None = None,
        limit: int = 100,
        min_abs_score: int = 50,
    ) -> dict[str, Any]: ...

    def promotion_dry_run_verification(
        self,
        *,
        candidate_parameter_set: str,
        production_parameter_set: str = PRODUCTION_PARAMETER_SET,
        decision_id: str | None = None,
        limit: int = 500,
        min_abs_score: int = 50,
    ) -> dict[str, Any]: ...

    def promotion_dry_run_acceptances(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def create_promotion_dry_run_acceptance(
        self,
        *,
        candidate_parameter_set: str,
        accepted_by: str,
        acceptance_rationale: str,
        decision_id: str | None = None,
        limit: int = 500,
        min_abs_score: int = 50,
    ) -> dict[str, Any]: ...

    def promotion_executions(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def promotion_rollback_drills(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def promotion_lifecycle_timeline(
        self,
        *,
        promotion_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def promotion_reconciliation(
        self,
        *,
        promotion_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def promotion_post_execution_monitoring(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def promotion_post_execution_alerts(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def rollback_promotion_execution(
        self,
        *,
        execution_id: str,
        operator_token_sha256: str,
        rollback_reason: str,
    ) -> dict[str, Any]: ...

    def symbol_chart(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
    ) -> dict[str, Any]: ...

    def symbol_whipsaw_risk(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]: ...


def _parameter_filter(alias: str, parameter_set: str | None) -> str:
    if parameter_set:
        return f"{alias}.name = %(parameter_set)s AND {alias}.is_active = TRUE"
    return f"{alias}.is_production = TRUE"


def fetch_latest_scores(
    conn: psycopg.Connection,
    *,
    limit: int,
    ticker: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    parameter_set: str | None = None,
) -> list[dict[str, Any]]:
    conditions = [_parameter_filter("p", parameter_set)]
    params: dict[str, Any] = {"limit": limit}
    if parameter_set:
        params["parameter_set"] = parameter_set

    if ticker:
        conditions.append("v.ticker = %(ticker)s")
        params["ticker"] = ticker.upper()
    if min_score is not None:
        conditions.append("v.composite_score >= %(min_score)s")
        params["min_score"] = min_score
    if max_score is not None:
        conditions.append("v.composite_score <= %(max_score)s")
        params["max_score"] = max_score

    where_clause = " AND ".join(conditions)
    sql = f"""
        WITH ranked AS (
            SELECT
                v.ticker,
                v.bar_date,
                v.parameter_set_id,
                v.parameter_set_name,
                v.dochia_version,
                v.monthly_state,
                v.weekly_state,
                v.daily_state,
                v.momentum_state,
                v.composite_score,
                v.computed_at,
                s.monthly_channel_high,
                s.monthly_channel_low,
                s.weekly_channel_high,
                s.weekly_channel_low,
                s.daily_channel_high,
                s.daily_channel_low,
                ROW_NUMBER() OVER (
                    PARTITION BY v.ticker
                    ORDER BY v.bar_date DESC, v.computed_at DESC
                ) AS rn
            FROM hedge_fund.v_signal_scores_composite v
            JOIN hedge_fund.signal_scores s
              ON s.ticker = v.ticker
             AND s.bar_date = v.bar_date
             AND s.parameter_set_id = v.parameter_set_id
            JOIN hedge_fund.scoring_parameters p ON p.id = v.parameter_set_id
            WHERE {where_clause}
        )
        SELECT
            ticker,
            bar_date,
            parameter_set_id,
            parameter_set_name,
            dochia_version,
            monthly_state,
            weekly_state,
            daily_state,
            momentum_state,
            composite_score,
            computed_at,
            monthly_channel_high,
            monthly_channel_low,
            weekly_channel_high,
            weekly_channel_low,
            daily_channel_high,
            daily_channel_low
        FROM ranked
        WHERE rn = 1
        ORDER BY composite_score DESC, ticker
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_recent_transitions(
    conn: psycopg.Connection,
    *,
    limit: int,
    ticker: str | None = None,
    transition_type: str | None = None,
    since: dt.date | None = None,
    lookback_days: int | None = None,
    parameter_set: str | None = None,
) -> list[dict[str, Any]]:
    conditions = [_parameter_filter("p", parameter_set)]
    params: dict[str, Any] = {"limit": limit}
    if parameter_set:
        params["parameter_set"] = parameter_set

    if ticker:
        conditions.append("t.ticker = %(ticker)s")
        params["ticker"] = ticker.upper()
    if transition_type:
        conditions.append("t.transition_type = %(transition_type)s")
        params["transition_type"] = transition_type
    if since is not None:
        conditions.append("t.to_bar_date >= %(since)s")
        params["since"] = since
    elif lookback_days is not None:
        conditions.append(
            f"""
            t.to_bar_date >= (
                SELECT COALESCE(MAX(t2.to_bar_date), CURRENT_DATE)
                FROM hedge_fund.signal_transitions t2
                JOIN hedge_fund.scoring_parameters p2 ON p2.id = t2.parameter_set_id
                WHERE {_parameter_filter("p2", parameter_set)}
            ) - %(lookback_days)s::int
            """
        )
        params["lookback_days"] = lookback_days

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT
            t.id,
            t.ticker,
            p.name AS parameter_set_name,
            t.transition_type,
            t.from_score,
            t.to_score,
            t.from_bar_date,
            t.to_bar_date,
            t.from_states,
            t.to_states,
            t.detected_at,
            t.acknowledged_by_user_id,
            t.acknowledged_at,
            t.notes
        FROM hedge_fund.signal_transitions t
        JOIN hedge_fund.scoring_parameters p ON p.id = t.parameter_set_id
        WHERE {where_clause}
        ORDER BY t.to_bar_date DESC, t.detected_at DESC, t.ticker
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _safe_average_score(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return sum(int(row["composite_score"]) for row in rows) / len(rows)


def _calibration_metric(calibration: dict[str, Any], key: str) -> float | None:
    value = calibration.get(key)
    if value is None:
        return None
    return float(value)


def _metric_delta(
    *,
    candidate: dict[str, Any],
    production: dict[str, Any],
    key: str,
) -> float | None:
    candidate_value = _calibration_metric(candidate, key)
    production_value = _calibration_metric(production, key)
    if candidate_value is None or production_value is None:
        return None
    return candidate_value - production_value


def _promotion_model_summary(
    *,
    id: str,
    label: str,
    parameter_set: str | None,
    latest_rows: list[dict[str, Any]],
    transition_rows: list[dict[str, Any]],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    latest_dates = [row["bar_date"] for row in latest_rows if row.get("bar_date") is not None]
    signal_count = len(latest_rows)
    bullish_count = sum(1 for row in latest_rows if int(row["composite_score"]) >= 50)
    risk_count = sum(1 for row in latest_rows if int(row["composite_score"]) <= -50)
    neutral_count = sum(1 for row in latest_rows if -30 <= int(row["composite_score"]) <= 30)
    reentry_count = sum(
        1 for row in transition_rows if str(row["transition_type"]) == "exit_to_reentry"
    )
    return {
        "id": id,
        "label": label,
        "parameter_set_name": str(calibration["parameter_set_name"]),
        "daily_trigger_mode": daily_trigger_mode_for_parameter_set(parameter_set).value,
        "latest_bar_date": max(latest_dates) if latest_dates else None,
        "signal_count": signal_count,
        "bullish_count": bullish_count,
        "risk_count": risk_count,
        "neutral_count": neutral_count,
        "reentry_count": reentry_count,
        "average_score": _safe_average_score(latest_rows),
        "calibration": {
            "total_observations": int(calibration["total_observations"]),
            "covered_observations": int(calibration["covered_observations"]),
            "accuracy": calibration["accuracy"],
            "exact_event_accuracy": calibration["exact_event_accuracy"],
            "window_event_accuracy": calibration["window_event_accuracy"],
            "coverage_rate": calibration["coverage_rate"],
            "exact_coverage_rate": calibration["exact_coverage_rate"],
            "score_mae": calibration["score_mae"],
            "score_rmse": calibration["score_rmse"],
        },
    }


def _promotion_guardrails(
    *,
    production: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, str]]:
    production_calibration = production["calibration"]
    candidate_calibration = candidate["calibration"]
    window_delta = _metric_delta(
        candidate=candidate_calibration,
        production=production_calibration,
        key="window_event_accuracy",
    )
    coverage_delta = _metric_delta(
        candidate=candidate_calibration,
        production=production_calibration,
        key="coverage_rate",
    )
    score_mae_delta = _metric_delta(
        candidate=candidate_calibration,
        production=production_calibration,
        key="score_mae",
    )
    production_signal_count = max(int(production["signal_count"]), 1)
    signal_count_delta_rate = (
        int(candidate["signal_count"]) - int(production["signal_count"])
    ) / production_signal_count

    window_status = "pass"
    if window_delta is None or window_delta < -0.03:
        window_status = "fail"
    elif window_delta < 0:
        window_status = "watch"

    coverage_status = "pass"
    candidate_coverage = _calibration_metric(candidate_calibration, "coverage_rate")
    if candidate_coverage is None or (
        candidate_coverage < 0.75 or (coverage_delta is not None and coverage_delta < -0.05)
    ):
        coverage_status = "fail"
    elif coverage_delta is not None and coverage_delta < -0.02:
        coverage_status = "watch"

    score_mae_status = "pass"
    if score_mae_delta is None or score_mae_delta > 8:
        score_mae_status = "fail"
    elif score_mae_delta > 3:
        score_mae_status = "watch"

    scanner_status = "pass"
    if candidate["signal_count"] == 0:
        scanner_status = "fail"
    elif abs(signal_count_delta_rate) > 0.35:
        scanner_status = "watch"

    return [
        {
            "id": "window_event_accuracy",
            "label": "Window alert match",
            "status": window_status,
            "detail": "Candidate should not materially trail production on ± window alert matches.",
        },
        {
            "id": "coverage_rate",
            "label": "Observation coverage",
            "status": coverage_status,
            "detail": "Candidate needs broad MarketClub observation coverage before promotion.",
        },
        {
            "id": "score_mae",
            "label": "Score error",
            "status": score_mae_status,
            "detail": "Candidate score error should stay close to production.",
        },
        {
            "id": "scanner_count",
            "label": "Scanner posture",
            "status": scanner_status,
            "detail": "Candidate should not radically collapse or inflate the visible signal book.",
        },
    ]


def _promotion_recommendation(guardrails: list[dict[str, str]]) -> dict[str, str]:
    statuses = {guardrail["status"] for guardrail in guardrails}
    if "fail" in statuses:
        return {
            "status": "hold",
            "label": "Hold promotion",
            "rationale": "One or more guardrails are below the promotion threshold.",
        }
    if "watch" in statuses:
        return {
            "status": "review",
            "label": "Review before promotion",
            "rationale": "No hard failure, but at least one metric needs human review.",
        }
    return {
        "status": "ready_for_shadow",
        "label": "Ready for shadow",
        "rationale": "Candidate clears the compact promotion gate for supervised shadow review.",
    }


def fetch_promotion_gate(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    since: dt.date | None = None,
    until: dt.date | None = None,
    top_tickers: int = 20,
    event_window_days: int = 3,
) -> dict[str, Any]:
    production_latest = fetch_latest_scores(conn, limit=500)
    candidate_latest = fetch_latest_scores(
        conn,
        limit=500,
        parameter_set=candidate_parameter_set,
    )
    production_transitions = fetch_recent_transitions(conn, limit=500, lookback_days=30)
    candidate_transitions = fetch_recent_transitions(
        conn,
        limit=500,
        lookback_days=30,
        parameter_set=candidate_parameter_set,
    )
    production_calibration = fetch_daily_calibration(
        conn,
        since=since,
        until=until,
        top_tickers=top_tickers,
        event_window_days=event_window_days,
    ).as_json_dict()
    candidate_calibration = fetch_daily_calibration(
        conn,
        since=since,
        until=until,
        parameter_set=candidate_parameter_set,
        top_tickers=top_tickers,
        event_window_days=event_window_days,
    ).as_json_dict()
    production = _promotion_model_summary(
        id="production",
        label="Production",
        parameter_set=None,
        latest_rows=production_latest,
        transition_rows=production_transitions,
        calibration=production_calibration,
    )
    candidate = _promotion_model_summary(
        id="candidate",
        label="v0.2 Range",
        parameter_set=candidate_parameter_set,
        latest_rows=candidate_latest,
        transition_rows=candidate_transitions,
        calibration=candidate_calibration,
    )
    deltas = {
        "window_event_accuracy": _metric_delta(
            candidate=candidate["calibration"],
            production=production["calibration"],
            key="window_event_accuracy",
        ),
        "exact_event_accuracy": _metric_delta(
            candidate=candidate["calibration"],
            production=production["calibration"],
            key="exact_event_accuracy",
        ),
        "coverage_rate": _metric_delta(
            candidate=candidate["calibration"],
            production=production["calibration"],
            key="coverage_rate",
        ),
        "score_mae": _metric_delta(
            candidate=candidate["calibration"],
            production=production["calibration"],
            key="score_mae",
        ),
        "signal_count": int(candidate["signal_count"]) - int(production["signal_count"]),
        "reentry_count": int(candidate["reentry_count"]) - int(production["reentry_count"]),
    }
    guardrails = _promotion_guardrails(production=production, candidate=candidate)
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "candidate_parameter_set": candidate_parameter_set,
        "baseline_parameter_set": PRODUCTION_PARAMETER_SET,
        "since": since,
        "until": until,
        "event_window_days": event_window_days,
        "production": production,
        "candidate": candidate,
        "deltas": deltas,
        "guardrails": guardrails,
        "recommendation": _promotion_recommendation(guardrails),
    }


LANE_LABELS = {
    "bullish_alignment": "Bullish Alignment",
    "risk_alignment": "Risk Alignment",
    "reentry": "Re-entry",
    "mixed_timeframes": "Mixed Timeframes",
}


def _lane_change_review(
    *,
    production_lanes: dict[str, list[dict[str, Any]]],
    candidate_lanes: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for lane_id, label in LANE_LABELS.items():
        production_tickers = [str(row["ticker"]) for row in production_lanes.get(lane_id, [])]
        candidate_tickers = [str(row["ticker"]) for row in candidate_lanes.get(lane_id, [])]
        production_set = set(production_tickers)
        candidate_set = set(candidate_tickers)
        added = sorted(candidate_set - production_set)
        removed = sorted(production_set - candidate_set)
        unchanged = sorted(candidate_set & production_set)
        universe = max(len(candidate_set | production_set), 1)
        reviews.append(
            {
                "lane_id": lane_id,
                "label": label,
                "production_tickers": production_tickers,
                "candidate_tickers": candidate_tickers,
                "added_tickers": added,
                "removed_tickers": removed,
                "unchanged_tickers": unchanged,
                "churn_rate": (len(added) + len(removed)) / universe,
            }
        )
    return reviews


def _transition_pressure_review(
    *,
    production_transitions: list[dict[str, Any]],
    candidate_transitions: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    production_counts = Counter(str(row["ticker"]) for row in production_transitions)
    candidate_counts = Counter(str(row["ticker"]) for row in candidate_transitions)
    latest_candidate: dict[str, dict[str, Any]] = {}
    for row in candidate_transitions:
        ticker = str(row["ticker"])
        latest_candidate.setdefault(ticker, row)

    ranked_tickers = sorted(
        candidate_counts,
        key=lambda ticker: (
            candidate_counts[ticker],
            candidate_counts[ticker] - production_counts.get(ticker, 0),
            ticker,
        ),
        reverse=True,
    )[:limit]
    reviews: list[dict[str, Any]] = []
    for ticker in ranked_tickers:
        latest = latest_candidate.get(ticker, {})
        reviews.append(
            {
                "ticker": ticker,
                "production_transition_count": production_counts.get(ticker, 0),
                "candidate_transition_count": candidate_counts[ticker],
                "delta": candidate_counts[ticker] - production_counts.get(ticker, 0),
                "latest_candidate_transition_type": latest.get("transition_type"),
                "latest_candidate_transition_date": latest.get("to_bar_date"),
            }
        )
    return reviews


def _shadow_whipsaw_review(
    conn: psycopg.Connection,
    *,
    tickers: list[str],
    candidate_parameter_set: str,
    whipsaw_window_sessions: int,
    outcome_horizon_sessions: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        risk = fetch_symbol_whipsaw_risk(
            conn,
            ticker=ticker,
            sessions=260,
            parameter_set=candidate_parameter_set,
            whipsaw_window_sessions=whipsaw_window_sessions,
            outcome_horizon_sessions=outcome_horizon_sessions,
        )
        rows.append(
            {
                "ticker": ticker,
                "risk_level": risk["risk_level"],
                "risk_score": risk["risk_score"],
                "event_count": risk["event_count"],
                "whipsaw_count": risk["whipsaw_count"],
                "whipsaw_rate": risk["whipsaw_rate"],
                "win_rate": risk["outcome"]["win_rate"],
                "average_directional_return": risk["outcome"]["average_directional_return"],
                "latest_whipsaw_date": risk["latest_whipsaw_date"],
            }
        )
    return sorted(rows, key=lambda row: (row["risk_score"], row["whipsaw_count"]), reverse=True)


def _shadow_review_checklist(
    *,
    gate: dict[str, Any],
    lane_reviews: list[dict[str, Any]],
    whipsaw_reviews: list[dict[str, Any]],
) -> list[dict[str, str]]:
    gate_status = gate["recommendation"]["status"]
    lane_churn = max((float(row["churn_rate"]) for row in lane_reviews), default=0.0)
    high_whipsaw_count = sum(1 for row in whipsaw_reviews if row["risk_level"] == "high")
    gate_check_status = {"ready_for_shadow": "pass", "hold": "hold"}.get(
        gate_status,
        "review",
    )

    return [
        {
            "id": "promotion_gate",
            "label": "Promotion Gate",
            "status": gate_check_status,
            "detail": gate["recommendation"]["rationale"],
        },
        {
            "id": "lane_churn",
            "label": "Lane Churn Review",
            "status": "review" if lane_churn >= 0.35 else "pass",
            "detail": f"Highest lane churn is {lane_churn:.0%}; review added and removed tickers before approval.",
        },
        {
            "id": "whipsaw_review",
            "label": "Whipsaw Review",
            "status": "review" if high_whipsaw_count else "pass",
            "detail": f"{high_whipsaw_count} reviewed ticker{'s' if high_whipsaw_count != 1 else ''} show high whipsaw risk.",
        },
        {
            "id": "decision_record",
            "label": "Human Decision Record",
            "status": "blocked",
            "detail": "A human promote/defer record is required before any market_signals write.",
        },
        {
            "id": "market_signals_write",
            "label": "market_signals Write",
            "status": "blocked",
            "detail": "This review is read-only; production signal promotion is intentionally disabled.",
        },
    ]


def _shadow_recommendation(
    *,
    gate: dict[str, Any],
    checklist: list[dict[str, str]],
) -> dict[str, str]:
    if gate["recommendation"]["status"] == "hold":
        return {
            "status": "hold",
            "label": "Hold promotion",
            "rationale": "Promotion Gate has a hard hold. Do not advance to market_signals.",
        }
    if any(item["status"] == "review" for item in checklist):
        return {
            "status": "needs_review",
            "label": "Needs human review",
            "rationale": "Evidence is ready, but lane churn or whipsaw pressure needs an explicit human decision.",
        }
    return {
        "status": "ready_for_shadow_review",
        "label": "Ready for shadow review",
        "rationale": "Evidence packet is ready for a supervised promote/defer decision.",
    }


def fetch_shadow_review(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    lookback_days: int = 30,
    review_limit: int = 8,
    whipsaw_window_sessions: int = 5,
    outcome_horizon_sessions: int = 5,
) -> dict[str, Any]:
    gate = fetch_promotion_gate(
        conn,
        candidate_parameter_set=candidate_parameter_set,
        top_tickers=review_limit,
    )
    production_lanes = fetch_watchlist_candidates(conn, limit=review_limit)
    candidate_lanes = fetch_watchlist_candidates(
        conn,
        limit=review_limit,
        parameter_set=candidate_parameter_set,
    )
    lane_reviews = _lane_change_review(
        production_lanes=production_lanes,
        candidate_lanes=candidate_lanes,
    )
    production_transitions = fetch_recent_transitions(
        conn,
        limit=500,
        lookback_days=lookback_days,
    )
    candidate_transitions = fetch_recent_transitions(
        conn,
        limit=500,
        lookback_days=lookback_days,
        parameter_set=candidate_parameter_set,
    )
    transition_pressure = _transition_pressure_review(
        production_transitions=production_transitions,
        candidate_transitions=candidate_transitions,
        limit=review_limit,
    )
    pressure_tickers = [row["ticker"] for row in transition_pressure]
    lane_tickers = [
        ticker
        for row in lane_reviews
        for ticker in [*row["added_tickers"], *row["removed_tickers"]]
    ]
    review_tickers = list(dict.fromkeys([*pressure_tickers, *lane_tickers]))[:review_limit]
    whipsaw_reviews = _shadow_whipsaw_review(
        conn,
        tickers=review_tickers,
        candidate_parameter_set=candidate_parameter_set,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
    )
    checklist = _shadow_review_checklist(
        gate=gate,
        lane_reviews=lane_reviews,
        whipsaw_reviews=whipsaw_reviews,
    )
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "candidate_parameter_set": candidate_parameter_set,
        "baseline_parameter_set": PRODUCTION_PARAMETER_SET,
        "lookback_days": lookback_days,
        "review_limit": review_limit,
        "promotion_gate": gate,
        "lane_reviews": lane_reviews,
        "transition_pressure": transition_pressure,
        "whipsaw_reviews": whipsaw_reviews,
        "checklist": checklist,
        "recommendation": _shadow_recommendation(gate=gate, checklist=checklist),
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _stable_json_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


SHADOW_DECISION_RECORD_SELECT = """
    SELECT
        id,
        candidate_parameter_set,
        baseline_parameter_set,
        decision,
        reviewer,
        rationale,
        rollback_criteria,
        reviewed_tickers,
        notes,
        shadow_review_generated_at,
        promotion_gate_status,
        recommendation_status,
        created_at
    FROM hedge_fund.signal_shadow_review_decisions
"""


def fetch_shadow_review_decision_records(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where = ""
    if candidate_parameter_set:
        where = "WHERE candidate_parameter_set = %(candidate_parameter_set)s"
        params["candidate_parameter_set"] = candidate_parameter_set
    sql = f"""
        {SHADOW_DECISION_RECORD_SELECT}
        {where}
        ORDER BY created_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def create_shadow_review_decision_record(
    conn: psycopg.Connection,
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
    evidence = fetch_shadow_review(
        conn,
        candidate_parameter_set=candidate_parameter_set,
        lookback_days=lookback_days,
        review_limit=review_limit,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
    )
    promotion_gate_status = evidence["promotion_gate"]["recommendation"]["status"]
    recommendation_status = evidence["recommendation"]["status"]
    if decision == "promote_to_market_signals" and recommendation_status == "hold":
        raise ValueError("Cannot record a promote decision while Shadow Review is on hold.")
    if decision == "promote_to_market_signals" and promotion_gate_status == "hold":
        raise ValueError("Cannot record a promote decision while Promotion Gate is on hold.")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO hedge_fund.signal_shadow_review_decisions (
                candidate_parameter_set,
                baseline_parameter_set,
                decision,
                reviewer,
                rationale,
                rollback_criteria,
                reviewed_tickers,
                notes,
                shadow_review_generated_at,
                promotion_gate_status,
                recommendation_status,
                evidence_payload
            ) VALUES (
                %(candidate_parameter_set)s,
                %(baseline_parameter_set)s,
                %(decision)s,
                %(reviewer)s,
                %(rationale)s,
                %(rollback_criteria)s,
                %(reviewed_tickers)s,
                %(notes)s,
                %(shadow_review_generated_at)s,
                %(promotion_gate_status)s,
                %(recommendation_status)s,
                %(evidence_payload)s
            )
            RETURNING *
            """,
            {
                "candidate_parameter_set": candidate_parameter_set,
                "baseline_parameter_set": evidence["baseline_parameter_set"],
                "decision": decision,
                "reviewer": reviewer,
                "rationale": rationale,
                "rollback_criteria": rollback_criteria,
                "reviewed_tickers": reviewed_tickers,
                "notes": notes,
                "shadow_review_generated_at": evidence["generated_at"],
                "promotion_gate_status": promotion_gate_status,
                "recommendation_status": recommendation_status,
                "evidence_payload": Jsonb(_json_safe(evidence)),
            },
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("shadow review decision insert returned no row")
    return {
        key: row[key]
        for key in [
            "id",
            "candidate_parameter_set",
            "baseline_parameter_set",
            "decision",
            "reviewer",
            "rationale",
            "rollback_criteria",
            "reviewed_tickers",
            "notes",
            "shadow_review_generated_at",
            "promotion_gate_status",
            "recommendation_status",
            "created_at",
        ]
    }


PROMOTION_DRY_RUN_TARGET_COLUMNS = [
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
]

VERIFICATION_PASS = "PASS"
VERIFICATION_FAIL = "FAIL"
VERIFICATION_INCONCLUSIVE = "INCONCLUSIVE"

CONFLICT_NONE = "NONE"
CONFLICT_CROSS_MODEL_DIAGNOSTIC_ONLY = "CROSS_MODEL_DIAGNOSTIC_ONLY"
CONFLICT_CANDIDATE_INTERNAL_CONFLICT = "CANDIDATE_INTERNAL_CONFLICT"
CONFLICT_SOURCE_LINEAGE_MISSING = "SOURCE_LINEAGE_MISSING"
CONFLICT_SOURCE_LINEAGE_DUPLICATE = "SOURCE_LINEAGE_DUPLICATE"
CONFLICT_SOURCE_LINEAGE_PARAMETER_MISMATCH = "SOURCE_LINEAGE_PARAMETER_MISMATCH"
CONFLICT_TRANSITION_UNSUPPORTED = "TRANSITION_UNSUPPORTED"

BULLISH_TRANSITIONS = {"breakout_bullish", "exit_to_reentry", "full_reversal"}
BEARISH_TRANSITIONS = {"breakout_bearish", "peak_to_exit", "full_reversal"}


def _latest_promote_decision_record(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    decision_id: str | None = None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"candidate_parameter_set": candidate_parameter_set}
    conditions = [
        "candidate_parameter_set = %(candidate_parameter_set)s",
        "decision = 'promote_to_market_signals'",
    ]
    if decision_id:
        conditions.append("id = %(decision_id)s")
        params["decision_id"] = decision_id
    where_clause = " AND ".join(conditions)
    sql = f"""
        {SHADOW_DECISION_RECORD_SELECT}
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT 1
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return dict(row) if row else None


def _promotion_dry_run_approval(
    decision: dict[str, Any] | None,
    *,
    decision_id: str | None,
) -> dict[str, Any]:
    if decision is None:
        detail = "No promote decision record found for this candidate."
        if decision_id:
            detail = "No promote decision record matched the supplied decision id."
        return {
            "status": "missing_promote_decision",
            "decision_id": None,
            "reviewer": None,
            "decision_created_at": None,
            "rollback_criteria": None,
            "detail": f"{detail} Dry-run remains preview-only.",
        }

    if (
        decision["promotion_gate_status"] == "hold"
        or decision["recommendation_status"] == "hold"
    ):
        return {
            "status": "blocked_by_review",
            "decision_id": decision["id"],
            "reviewer": decision["reviewer"],
            "decision_created_at": decision["created_at"],
            "rollback_criteria": decision["rollback_criteria"],
            "detail": "Promote record exists, but the captured review status is on hold.",
        }

    return {
        "status": "ready_for_dry_run",
        "decision_id": decision["id"],
        "reviewer": decision["reviewer"],
        "decision_created_at": decision["created_at"],
        "rollback_criteria": decision["rollback_criteria"],
        "detail": "Promote record found; dry-run can be reviewed before any guarded write path.",
    }


def _score_state_label(value: int) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "neutral"


def _market_signal_action(score: int) -> str:
    if score >= 0:
        return "BUY"
    return "SELL"


def _promotion_signal_type(score: int) -> str:
    if score >= 50:
        return "Dochia bullish alignment"
    if score <= -50:
        return "Dochia risk alignment"
    return "Dochia watch"


def _promotion_raw_reasoning(row: dict[str, Any]) -> str:
    score = int(row["composite_score"])
    states = {
        "monthly": _score_state_label(int(row["monthly_state"])),
        "weekly": _score_state_label(int(row["weekly_state"])),
        "daily": _score_state_label(int(row["daily_state"])),
        "momentum": _score_state_label(int(row["momentum_state"])),
    }
    state_text = ", ".join(f"{key}={value}" for key, value in states.items())
    return (
        f"Dochia dry-run signal for {row['ticker']}: composite score {score:+d}; "
        f"{state_text}; candidate bar {row['bar_date']}."
    )


def _promotion_lineage(row: dict[str, Any], *, candidate_parameter_set: str) -> dict[str, Any]:
    score = int(row["composite_score"])
    states = {
        "monthly": int(row["monthly_state"]),
        "weekly": int(row["weekly_state"]),
        "daily": int(row["daily_state"]),
        "momentum": int(row["momentum_state"]),
    }
    return {
        "source_pipeline": "dochia_signal_scores",
        "parameter_set": candidate_parameter_set,
        "model_version": str(row["dochia_version"]),
        "computed_at": row["computed_at"],
        "explanation_payload": {
            "ticker": row["ticker"],
            "bar_date": row["bar_date"],
            "composite_score": score,
            "states": states,
            "daily_trigger_mode": daily_trigger_mode_for_parameter_set(
                candidate_parameter_set
            ).value,
            "channels": {
                "monthly_high": row["monthly_channel_high"],
                "monthly_low": row["monthly_channel_low"],
                "weekly_high": row["weekly_channel_high"],
                "weekly_low": row["weekly_channel_low"],
                "daily_high": row["daily_channel_high"],
                "daily_low": row["daily_channel_low"],
            },
        },
        "rollback_marker": (
            f"dochia-dry-run:{candidate_parameter_set}:{row['ticker']}:{row['bar_date']}"
        ),
    }


def _promotion_dry_run_row(
    row: dict[str, Any],
    *,
    candidate_parameter_set: str,
) -> dict[str, Any]:
    score = int(row["composite_score"])
    return {
        "ticker": row["ticker"],
        "action": _market_signal_action(score),
        "signal_type": _promotion_signal_type(score),
        "confidence_score": min(100, max(1, abs(score))),
        "price_target": None,
        "source_sender": "Dochia Signal Engine",
        "source_subject": f"Dry-run promotion {candidate_parameter_set}",
        "raw_reasoning": _promotion_raw_reasoning(row),
        "model_used": str(row["dochia_version"]),
        "extracted_at": row["computed_at"],
        "candidate_bar_date": row["bar_date"],
        "composite_score": score,
        "lineage": _promotion_lineage(row, candidate_parameter_set=candidate_parameter_set),
    }


def fetch_promotion_dry_run(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    decision_id: str | None = None,
    limit: int = 100,
    min_abs_score: int = 50,
) -> dict[str, Any]:
    generated_at = dt.datetime.now(dt.UTC)
    decision = _latest_promote_decision_record(
        conn,
        candidate_parameter_set=candidate_parameter_set,
        decision_id=decision_id,
    )
    candidate_rows = fetch_latest_scores(
        conn,
        limit=500,
        parameter_set=candidate_parameter_set,
    )
    eligible_rows: list[dict[str, Any]] = []
    skipped_neutral_count = 0
    for row in candidate_rows:
        score = int(row["composite_score"])
        if abs(score) < min_abs_score:
            skipped_neutral_count += 1
            continue
        eligible_rows.append(row)
    eligible_rows.sort(
        key=lambda row: (-abs(int(row["composite_score"])), str(row["ticker"]))
    )
    proposed_rows = [
        _promotion_dry_run_row(row, candidate_parameter_set=candidate_parameter_set)
        for row in eligible_rows[:limit]
    ]

    latest_dates = [row["bar_date"] for row in candidate_rows if row.get("bar_date")]
    bullish_count = sum(1 for row in proposed_rows if row["action"] == "BUY")
    risk_count = sum(1 for row in proposed_rows if row["action"] == "SELL")
    return {
        "generated_at": generated_at,
        "candidate_parameter_set": candidate_parameter_set,
        "baseline_parameter_set": PRODUCTION_PARAMETER_SET,
        "approval": _promotion_dry_run_approval(decision, decision_id=decision_id),
        "summary": {
            "target_table": "hedge_fund.market_signals",
            "target_columns": PROMOTION_DRY_RUN_TARGET_COLUMNS,
            "write_path_enabled": False,
            "candidate_signal_count": len(candidate_rows),
            "proposed_insert_count": len(proposed_rows),
            "bullish_count": bullish_count,
            "risk_count": risk_count,
            "skipped_neutral_count": skipped_neutral_count,
            "latest_bar_date": max(latest_dates) if latest_dates else None,
            "min_abs_score": min_abs_score,
        },
        "proposed_rows": proposed_rows,
    }


def _verification_action(score: int) -> str:
    return "BUY" if score >= 0 else "SELL"


def _verification_key(row: dict[str, Any]) -> tuple[str, dt.date]:
    bar_date = row.get("bar_date") or row.get("candidate_bar_date")
    if not isinstance(bar_date, dt.date):
        raise TypeError(f"verification row has non-date bar: {bar_date!r}")
    return str(row["ticker"]), bar_date


def _group_rows_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, dt.date], list[dict[str, Any]]]:
    grouped: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_verification_key(row), []).append(row)
    return grouped


def _latest_transition_for(
    transitions: list[dict[str, Any]],
    *,
    ticker: str,
    bar_date: dt.date,
) -> dict[str, Any] | None:
    eligible = [
        transition
        for transition in transitions
        if transition.get("ticker") == ticker and transition.get("to_bar_date") <= bar_date
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda transition: (
            transition.get("to_bar_date") or dt.date.min,
            transition.get("detected_at") or dt.datetime.min.replace(tzinfo=dt.UTC),
        ),
        reverse=True,
    )[0]


def _transition_supports_state(
    transition: dict[str, Any] | None,
    *,
    score: int,
    candidate_monthly: int,
    candidate_weekly: int,
    candidate_daily: int,
) -> tuple[bool, str]:
    if score >= 50:
        if candidate_monthly == 1 and candidate_weekly == 1 and candidate_daily == 1:
            return True, "Candidate is fully aligned monthly/weekly/daily bullish."
        if transition and str(transition.get("transition_type")) in BULLISH_TRANSITIONS:
            to_states = transition.get("to_states") or {}
            if int(transition.get("to_score") or 0) == score and int(to_states.get("daily", 0)) == 1:
                return True, "Latest candidate transition supports bullish resolved state."
        return False, "BUY row is not fully aligned and lacks a supporting bullish transition."

    if score <= -50:
        if candidate_monthly == -1 and candidate_weekly == -1 and candidate_daily == -1:
            return True, "Candidate is fully aligned monthly/weekly/daily bearish."
        if transition and str(transition.get("transition_type")) in BEARISH_TRANSITIONS:
            to_states = transition.get("to_states") or {}
            if int(transition.get("to_score") or 0) == score and int(to_states.get("daily", 0)) == -1:
                return True, "Latest candidate transition supports bearish resolved state."
        return False, "SELL row is not fully aligned and lacks a supporting bearish transition."

    return True, "Dry-run row is below strong promotion threshold."


def verify_promotion_dry_run_payload(
    *,
    dry_run: dict[str, Any],
    candidate_source_rows: list[dict[str, Any]],
    production_source_rows: list[dict[str, Any]],
    candidate_transition_rows: list[dict[str, Any]],
    candidate_parameter_set: str,
    production_parameter_set: str = PRODUCTION_PARAMETER_SET,
) -> dict[str, Any]:
    candidate_by_key = _group_rows_by_key(candidate_source_rows)
    production_by_key = _group_rows_by_key(production_source_rows)
    verification_rows: list[dict[str, Any]] = []

    for dry_row in dry_run["proposed_rows"]:
        ticker = str(dry_row["ticker"])
        bar_date = dry_row["candidate_bar_date"]
        key = (ticker, bar_date)
        candidate_rows = candidate_by_key.get(key, [])
        production_rows = production_by_key.get(key, [])
        latest_transition = _latest_transition_for(
            candidate_transition_rows,
            ticker=ticker,
            bar_date=bar_date,
        )

        row_status = VERIFICATION_PASS
        conflict_type = CONFLICT_NONE
        explanation_parts: list[str] = []
        candidate_source = candidate_rows[0] if len(candidate_rows) == 1 else None
        production_source = production_rows[0] if production_rows else None

        candidate_score: int | None = None
        candidate_action = str(dry_row["action"])
        candidate_monthly: int | None = None
        candidate_weekly: int | None = None
        candidate_daily: int | None = None

        if not candidate_rows:
            row_status = VERIFICATION_INCONCLUSIVE
            conflict_type = CONFLICT_SOURCE_LINEAGE_MISSING
            explanation_parts.append("No candidate source row traces to the dry-run ticker/bar.")
        elif len(candidate_rows) > 1:
            row_status = VERIFICATION_FAIL
            conflict_type = CONFLICT_SOURCE_LINEAGE_DUPLICATE
            explanation_parts.append("More than one candidate source row exists for the dry-run ticker/bar.")
        elif str(candidate_source.get("parameter_set_name")) != candidate_parameter_set:
            row_status = VERIFICATION_FAIL
            conflict_type = CONFLICT_SOURCE_LINEAGE_PARAMETER_MISMATCH
            explanation_parts.append("Candidate source row uses the wrong parameter set.")
        else:
            candidate_score = int(candidate_source["composite_score"])
            candidate_action = _verification_action(candidate_score)
            candidate_monthly = int(candidate_source["monthly_state"])
            candidate_weekly = int(candidate_source["weekly_state"])
            candidate_daily = int(candidate_source["daily_state"])
            dry_score = int(dry_row["composite_score"])
            dry_action = str(dry_row["action"])
            lineage = dry_row.get("lineage") or {}
            lineage_parameter = lineage.get("parameter_set")

            if lineage_parameter != candidate_parameter_set:
                row_status = VERIFICATION_FAIL
                conflict_type = CONFLICT_SOURCE_LINEAGE_PARAMETER_MISMATCH
                explanation_parts.append("Dry-run lineage parameter does not match the candidate parameter set.")
            elif dry_score != candidate_score or dry_action != candidate_action:
                row_status = VERIFICATION_FAIL
                conflict_type = CONFLICT_CANDIDATE_INTERNAL_CONFLICT
                explanation_parts.append("Dry-run row does not match the candidate source score/action.")
            elif dry_action == "BUY" and candidate_daily < 0:
                row_status = VERIFICATION_FAIL
                conflict_type = CONFLICT_CANDIDATE_INTERNAL_CONFLICT
                explanation_parts.append("Candidate proposes BUY while candidate daily triangle is bearish.")
            elif dry_action == "SELL" and candidate_daily > 0:
                row_status = VERIFICATION_FAIL
                conflict_type = CONFLICT_CANDIDATE_INTERNAL_CONFLICT
                explanation_parts.append("Candidate proposes SELL while candidate daily triangle is bullish.")
            else:
                supported, support_explanation = _transition_supports_state(
                    latest_transition,
                    score=candidate_score,
                    candidate_monthly=candidate_monthly,
                    candidate_weekly=candidate_weekly,
                    candidate_daily=candidate_daily,
                )
                if not supported:
                    row_status = VERIFICATION_INCONCLUSIVE
                    conflict_type = CONFLICT_TRANSITION_UNSUPPORTED
                explanation_parts.append(support_explanation)

            if row_status == VERIFICATION_PASS and production_source:
                production_score = int(production_source["composite_score"])
                production_daily = int(production_source["daily_state"])
                if production_score != candidate_score or production_daily != candidate_daily:
                    conflict_type = CONFLICT_CROSS_MODEL_DIAGNOSTIC_ONLY
                    explanation_parts.append(
                        "Production baseline differs from candidate, but candidate lineage is clean."
                    )

        production_score = (
            int(production_source["composite_score"]) if production_source else None
        )
        production_daily = int(production_source["daily_state"]) if production_source else None
        verification_rows.append(
            {
                "row_status": row_status,
                "ticker": ticker,
                "candidate_bar_date": bar_date,
                "candidate_score": candidate_score,
                "candidate_action": candidate_action,
                "candidate_monthly_triangle": candidate_monthly,
                "candidate_weekly_triangle": candidate_weekly,
                "candidate_daily_triangle": candidate_daily,
                "latest_candidate_transition_date": (
                    latest_transition.get("to_bar_date") if latest_transition else None
                ),
                "latest_candidate_transition_type": (
                    latest_transition.get("transition_type") if latest_transition else None
                ),
                "prior_score": latest_transition.get("from_score") if latest_transition else None,
                "new_score": latest_transition.get("to_score") if latest_transition else None,
                "production_score": production_score,
                "production_daily_triangle": production_daily,
                "conflict_type": conflict_type,
                "explanation": " ".join(explanation_parts),
            }
        )

    if any(row["row_status"] == VERIFICATION_FAIL for row in verification_rows):
        overall_status = VERIFICATION_FAIL
    elif any(row["row_status"] == VERIFICATION_INCONCLUSIVE for row in verification_rows):
        overall_status = VERIFICATION_INCONCLUSIVE
    else:
        overall_status = VERIFICATION_PASS

    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "candidate_parameter_set": candidate_parameter_set,
        "production_parameter_set": production_parameter_set,
        "overall_status": overall_status,
        "proposed_rows_checked": len(verification_rows),
        "passed_rows": sum(row["row_status"] == VERIFICATION_PASS for row in verification_rows),
        "failed_rows": sum(row["row_status"] == VERIFICATION_FAIL for row in verification_rows),
        "inconclusive_rows": sum(
            row["row_status"] == VERIFICATION_INCONCLUSIVE for row in verification_rows
        ),
        "cross_model_diagnostic_only_rows": sum(
            row["conflict_type"] == CONFLICT_CROSS_MODEL_DIAGNOSTIC_ONLY
            for row in verification_rows
        ),
        "rows": verification_rows,
    }


def _fetch_source_rows_for_dry_run(
    conn: psycopg.Connection,
    *,
    dry_run: dict[str, Any],
    parameter_set: str,
) -> list[dict[str, Any]]:
    proposed_rows = dry_run["proposed_rows"]
    if not proposed_rows:
        return []
    tickers = sorted({row["ticker"] for row in proposed_rows})
    bar_dates = sorted({row["candidate_bar_date"] for row in proposed_rows})
    sql = """
        SELECT
            v.ticker,
            v.bar_date,
            v.parameter_set_id,
            v.parameter_set_name,
            v.dochia_version,
            v.monthly_state,
            v.weekly_state,
            v.daily_state,
            v.momentum_state,
            v.composite_score,
            v.computed_at,
            s.monthly_channel_high,
            s.monthly_channel_low,
            s.weekly_channel_high,
            s.weekly_channel_low,
            s.daily_channel_high,
            s.daily_channel_low
        FROM hedge_fund.v_signal_scores_composite v
        JOIN hedge_fund.signal_scores s
          ON s.ticker = v.ticker
         AND s.bar_date = v.bar_date
         AND s.parameter_set_id = v.parameter_set_id
        WHERE v.parameter_set_name = %(parameter_set)s
          AND v.ticker = ANY(%(tickers)s)
          AND v.bar_date = ANY(%(bar_dates)s)
        ORDER BY v.ticker, v.bar_date, v.computed_at DESC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql,
            {
                "parameter_set": parameter_set,
                "tickers": tickers,
                "bar_dates": bar_dates,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def _fetch_candidate_transitions_for_dry_run(
    conn: psycopg.Connection,
    *,
    dry_run: dict[str, Any],
    candidate_parameter_set: str,
) -> list[dict[str, Any]]:
    proposed_rows = dry_run["proposed_rows"]
    if not proposed_rows:
        return []
    tickers = sorted({row["ticker"] for row in proposed_rows})
    latest_bar_date = max(row["candidate_bar_date"] for row in proposed_rows)
    sql = """
        SELECT
            t.id,
            t.ticker,
            p.name AS parameter_set_name,
            t.transition_type,
            t.from_score,
            t.to_score,
            t.from_bar_date,
            t.to_bar_date,
            t.from_states,
            t.to_states,
            t.detected_at,
            t.acknowledged_by_user_id,
            t.acknowledged_at,
            t.notes
        FROM hedge_fund.signal_transitions t
        JOIN hedge_fund.scoring_parameters p ON p.id = t.parameter_set_id
        WHERE p.name = %(candidate_parameter_set)s
          AND t.ticker = ANY(%(tickers)s)
          AND t.to_bar_date <= %(latest_bar_date)s
        ORDER BY t.ticker, t.to_bar_date DESC, t.detected_at DESC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql,
            {
                "candidate_parameter_set": candidate_parameter_set,
                "tickers": tickers,
                "latest_bar_date": latest_bar_date,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def _verify_promotion_dry_run_from_payload(
    conn: psycopg.Connection,
    *,
    dry_run: dict[str, Any],
    candidate_parameter_set: str,
    production_parameter_set: str,
) -> dict[str, Any]:
    candidate_source_rows = _fetch_source_rows_for_dry_run(
        conn,
        dry_run=dry_run,
        parameter_set=candidate_parameter_set,
    )
    production_source_rows = _fetch_source_rows_for_dry_run(
        conn,
        dry_run=dry_run,
        parameter_set=production_parameter_set,
    )
    candidate_transition_rows = _fetch_candidate_transitions_for_dry_run(
        conn,
        dry_run=dry_run,
        candidate_parameter_set=candidate_parameter_set,
    )
    return verify_promotion_dry_run_payload(
        dry_run=dry_run,
        candidate_source_rows=candidate_source_rows,
        production_source_rows=production_source_rows,
        candidate_transition_rows=candidate_transition_rows,
        candidate_parameter_set=candidate_parameter_set,
        production_parameter_set=production_parameter_set,
    )


def fetch_promotion_dry_run_verification(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    production_parameter_set: str = PRODUCTION_PARAMETER_SET,
    decision_id: str | None = None,
    limit: int = 500,
    min_abs_score: int = 50,
) -> dict[str, Any]:
    dry_run = fetch_promotion_dry_run(
        conn,
        candidate_parameter_set=candidate_parameter_set,
        decision_id=decision_id,
        limit=limit,
        min_abs_score=min_abs_score,
    )
    return _verify_promotion_dry_run_from_payload(
        conn,
        dry_run=dry_run,
        candidate_parameter_set=candidate_parameter_set,
        production_parameter_set=production_parameter_set,
    )


PROMOTION_DRY_RUN_ACCEPTANCE_SELECT = """
    SELECT
        id,
        decision_record_id,
        candidate_parameter_set,
        baseline_parameter_set,
        accepted_by,
        acceptance_rationale,
        rollback_criteria,
        dry_run_generated_at,
        dry_run_candidate_signal_count,
        dry_run_proposed_insert_count,
        dry_run_bullish_count,
        dry_run_risk_count,
        dry_run_skipped_neutral_count,
        min_abs_score,
        target_table,
        target_columns,
        created_at
    FROM hedge_fund.signal_promotion_dry_run_acceptances
"""


def fetch_promotion_dry_run_acceptances(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where = ""
    if candidate_parameter_set:
        where = "WHERE candidate_parameter_set = %(candidate_parameter_set)s"
        params["candidate_parameter_set"] = candidate_parameter_set
    sql = f"""
        {PROMOTION_DRY_RUN_ACCEPTANCE_SELECT}
        {where}
        ORDER BY created_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def create_promotion_dry_run_acceptance(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str,
    accepted_by: str,
    acceptance_rationale: str,
    decision_id: str | None = None,
    limit: int = 500,
    min_abs_score: int = 50,
) -> dict[str, Any]:
    dry_run = fetch_promotion_dry_run(
        conn,
        candidate_parameter_set=candidate_parameter_set,
        decision_id=decision_id,
        limit=limit,
        min_abs_score=min_abs_score,
    )
    approval = dry_run["approval"]
    if approval["status"] != "ready_for_dry_run":
        raise ValueError("Cannot accept dry-run output without a ready promote decision record.")
    if dry_run["summary"]["proposed_insert_count"] == 0:
        raise ValueError("Cannot accept dry-run output with no proposed market_signals rows.")
    verification = _verify_promotion_dry_run_from_payload(
        conn,
        dry_run=dry_run,
        candidate_parameter_set=candidate_parameter_set,
        production_parameter_set=PRODUCTION_PARAMETER_SET,
    )
    if verification["overall_status"] != VERIFICATION_PASS:
        raise ValueError(
            "Dry-run verification gate blocked acceptance: "
            f"{verification['overall_status']}."
        )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO hedge_fund.signal_promotion_dry_run_acceptances (
                decision_record_id,
                candidate_parameter_set,
                baseline_parameter_set,
                accepted_by,
                acceptance_rationale,
                rollback_criteria,
                dry_run_generated_at,
                dry_run_candidate_signal_count,
                dry_run_proposed_insert_count,
                dry_run_bullish_count,
                dry_run_risk_count,
                dry_run_skipped_neutral_count,
                min_abs_score,
                target_table,
                target_columns,
                dry_run_payload,
                verification_status_snapshot,
                verification_payload_snapshot,
                candidate_set_hash
            ) VALUES (
                %(decision_record_id)s,
                %(candidate_parameter_set)s,
                %(baseline_parameter_set)s,
                %(accepted_by)s,
                %(acceptance_rationale)s,
                %(rollback_criteria)s,
                %(dry_run_generated_at)s,
                %(dry_run_candidate_signal_count)s,
                %(dry_run_proposed_insert_count)s,
                %(dry_run_bullish_count)s,
                %(dry_run_risk_count)s,
                %(dry_run_skipped_neutral_count)s,
                %(min_abs_score)s,
                %(target_table)s,
                %(target_columns)s,
                %(dry_run_payload)s,
                %(verification_status_snapshot)s,
                %(verification_payload_snapshot)s,
                %(candidate_set_hash)s
            )
            RETURNING *
            """,
            {
                "decision_record_id": approval["decision_id"],
                "candidate_parameter_set": candidate_parameter_set,
                "baseline_parameter_set": dry_run["baseline_parameter_set"],
                "accepted_by": accepted_by,
                "acceptance_rationale": acceptance_rationale,
                "rollback_criteria": approval["rollback_criteria"] or "",
                "dry_run_generated_at": dry_run["generated_at"],
                "dry_run_candidate_signal_count": dry_run["summary"]["candidate_signal_count"],
                "dry_run_proposed_insert_count": dry_run["summary"]["proposed_insert_count"],
                "dry_run_bullish_count": dry_run["summary"]["bullish_count"],
                "dry_run_risk_count": dry_run["summary"]["risk_count"],
                "dry_run_skipped_neutral_count": dry_run["summary"]["skipped_neutral_count"],
                "min_abs_score": min_abs_score,
                "target_table": dry_run["summary"]["target_table"],
                "target_columns": dry_run["summary"]["target_columns"],
                "dry_run_payload": Jsonb(_json_safe(dry_run)),
                "verification_status_snapshot": verification["overall_status"],
                "verification_payload_snapshot": Jsonb(_json_safe(verification)),
                "candidate_set_hash": _stable_json_hash(dry_run["proposed_rows"]),
            },
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("promotion dry-run acceptance insert returned no row")
    return {
        key: row[key]
        for key in [
            "id",
            "decision_record_id",
            "candidate_parameter_set",
            "baseline_parameter_set",
            "accepted_by",
            "acceptance_rationale",
            "rollback_criteria",
            "dry_run_generated_at",
            "dry_run_candidate_signal_count",
            "dry_run_proposed_insert_count",
            "dry_run_bullish_count",
            "dry_run_risk_count",
            "dry_run_skipped_neutral_count",
            "min_abs_score",
            "target_table",
            "target_columns",
            "created_at",
        ]
    }


PROMOTION_EXECUTION_SELECT = """
    SELECT
        id,
        acceptance_id,
        decision_record_id,
        candidate_parameter_set,
        baseline_parameter_set,
        operator_membership_id,
        executed_by,
        execution_rationale,
        idempotency_key,
        dry_run_generated_at,
        dry_run_proposed_insert_count,
        verification_status,
        inserted_market_signal_ids,
        rollback_markers,
        rollback_status,
        rollback_operator_membership_id,
        rollback_by,
        rollback_reason,
        rolled_back_at,
        created_at
    FROM hedge_fund.signal_promotion_executions
"""


PROMOTION_EXECUTION_FIELDS = [
    "id",
    "acceptance_id",
    "decision_record_id",
    "candidate_parameter_set",
    "baseline_parameter_set",
    "operator_membership_id",
    "executed_by",
    "execution_rationale",
    "idempotency_key",
    "dry_run_generated_at",
    "dry_run_proposed_insert_count",
    "verification_status",
    "inserted_market_signal_ids",
    "rollback_markers",
    "rollback_status",
    "rollback_operator_membership_id",
    "rollback_by",
    "rollback_reason",
    "rolled_back_at",
    "created_at",
]


def _promotion_execution_response(row: dict[str, Any]) -> dict[str, Any]:
    response = {key: row[key] for key in PROMOTION_EXECUTION_FIELDS}
    response["inserted_market_signal_ids"] = list(response["inserted_market_signal_ids"] or [])
    response["rollback_markers"] = list(response["rollback_markers"] or [])
    return response


def fetch_promotion_executions(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where = ""
    if candidate_parameter_set:
        where = "WHERE candidate_parameter_set = %(candidate_parameter_set)s"
        params["candidate_parameter_set"] = candidate_parameter_set
    sql = f"""
        {PROMOTION_EXECUTION_SELECT}
        {where}
        ORDER BY created_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [_promotion_execution_response(dict(row)) for row in cur.fetchall()]


PROMOTION_ROLLBACK_DRILL_SELECT = """
    SELECT
        execution_id,
        dry_run_acceptance_id,
        candidate_parameter_set,
        baseline_parameter_set,
        executed_by,
        executed_at,
        inserted_market_signal_ids,
        rollback_markers,
        audited_market_signal_ids,
        rollback_preview_market_signal_ids,
        rollback_preview_count,
        rollback_eligibility,
        rollback_eligible,
        already_rolled_back,
        rollback_status,
        rollback_by,
        rollback_attempted_at,
        rolled_back_at
    FROM hedge_fund.v_signal_promotion_rollback_drill
"""


PROMOTION_ROLLBACK_DRILL_FIELDS = [
    "execution_id",
    "dry_run_acceptance_id",
    "candidate_parameter_set",
    "baseline_parameter_set",
    "executed_by",
    "executed_at",
    "inserted_market_signal_ids",
    "rollback_markers",
    "audited_market_signal_ids",
    "rollback_preview_market_signal_ids",
    "rollback_preview_count",
    "rollback_eligibility",
    "rollback_eligible",
    "already_rolled_back",
    "rollback_status",
    "rollback_by",
    "rollback_attempted_at",
    "rolled_back_at",
]


def _promotion_rollback_drill_response(row: dict[str, Any]) -> dict[str, Any]:
    response = {key: row[key] for key in PROMOTION_ROLLBACK_DRILL_FIELDS}
    response["inserted_market_signal_ids"] = list(response["inserted_market_signal_ids"] or [])
    response["rollback_markers"] = list(response["rollback_markers"] or [])
    response["audited_market_signal_ids"] = list(response["audited_market_signal_ids"] or [])
    response["rollback_preview_market_signal_ids"] = list(
        response["rollback_preview_market_signal_ids"] or []
    )
    return response


def fetch_promotion_rollback_drills(
    conn: psycopg.Connection,
    *,
    candidate_parameter_set: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where = ""
    if candidate_parameter_set:
        where = "WHERE candidate_parameter_set = %(candidate_parameter_set)s"
        params["candidate_parameter_set"] = candidate_parameter_set
    sql = f"""
        {PROMOTION_ROLLBACK_DRILL_SELECT}
        {where}
        ORDER BY executed_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [_promotion_rollback_drill_response(dict(row)) for row in cur.fetchall()]


PROMOTION_LIFECYCLE_TIMELINE_FIELDS = [
    "ts",
    "event_type",
    "decision_id",
    "acceptance_id",
    "execution_id",
    "candidate_id",
    "actor",
    "meta",
]


def fetch_promotion_lifecycle_timeline(
    conn: psycopg.Connection,
    *,
    promotion_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            ts,
            event_type,
            decision_id,
            acceptance_id,
            execution_id,
            candidate_id,
            actor,
            meta
        FROM hedge_fund.v_signal_promotion_lifecycle_timeline
        WHERE candidate_id = %(promotion_id)s
           OR decision_id::TEXT = %(promotion_id)s
           OR acceptance_id::TEXT = %(promotion_id)s
           OR execution_id::TEXT = %(promotion_id)s
        ORDER BY ts DESC, event_type DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"promotion_id": promotion_id, "limit": limit})
        rows: list[dict[str, Any]] = []
        for row in cur.fetchall():
            payload = {key: row[key] for key in PROMOTION_LIFECYCLE_TIMELINE_FIELDS}
            payload["type"] = payload.pop("event_type")
            rows.append(payload)
        return rows


PROMOTION_RECONCILIATION_FIELDS = [
    "execution_id",
    "acceptance_id",
    "candidate_id",
    "status",
    "checks",
    "warnings",
    "drilldown",
    "explanation",
]


def fetch_promotion_reconciliation(
    conn: psycopg.Connection,
    *,
    promotion_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            execution_id,
            acceptance_id,
            candidate_id,
            status,
            checks,
            warnings,
            drilldown,
            explanation
        FROM hedge_fund.v_signal_promotion_reconciliation
        WHERE candidate_id = %(promotion_id)s
           OR acceptance_id::TEXT = %(promotion_id)s
           OR execution_id::TEXT = %(promotion_id)s
        ORDER BY
            CASE status WHEN 'ERROR' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
            execution_id DESC NULLS LAST
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"promotion_id": promotion_id, "limit": limit})
        return [
            {key: row[key] for key in PROMOTION_RECONCILIATION_FIELDS}
            for row in cur.fetchall()
        ]


PROMOTION_POST_EXECUTION_MONITORING_FIELDS = [
    "execution_id",
    "acceptance_id",
    "decision_record_id",
    "candidate_id",
    "baseline_parameter_set",
    "executed_by",
    "executed_at",
    "rollback_status",
    "market_signal_id",
    "market_signal_live",
    "ticker",
    "action",
    "confidence_score",
    "candidate_bar_date",
    "rollback_marker",
    "candidate_score",
    "candidate_monthly_triangle",
    "candidate_weekly_triangle",
    "candidate_daily_triangle",
    "entry_close",
    "outcome_1d_bar_date",
    "outcome_1d_close",
    "outcome_1d_directional_return",
    "outcome_5d_bar_date",
    "outcome_5d_close",
    "outcome_5d_directional_return",
    "outcome_20d_bar_date",
    "outcome_20d_close",
    "outcome_20d_directional_return",
    "latest_candidate_bar_date",
    "latest_candidate_score",
    "latest_monthly_triangle",
    "latest_weekly_triangle",
    "latest_daily_triangle",
    "score_delta",
    "signal_decay_flag",
    "signal_decay_date",
    "signal_decay_score",
    "signal_decay_daily_triangle",
    "whipsaw_after_promotion_flag",
    "whipsaw_transition_date",
    "whipsaw_transition_type",
    "whipsaw_to_score",
    "drift_status",
    "rollback_recommendation",
    "monitoring_status",
    "explanation",
]


def fetch_promotion_post_execution_monitoring(
    conn: psycopg.Connection,
    *,
    promotion_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    sql = """
        SELECT
            execution_id,
            acceptance_id,
            decision_record_id,
            candidate_id,
            baseline_parameter_set,
            executed_by,
            executed_at,
            rollback_status,
            market_signal_id,
            market_signal_live,
            ticker,
            action,
            confidence_score,
            candidate_bar_date,
            rollback_marker,
            candidate_score,
            candidate_monthly_triangle,
            candidate_weekly_triangle,
            candidate_daily_triangle,
            entry_close,
            outcome_1d_bar_date,
            outcome_1d_close,
            outcome_1d_directional_return,
            outcome_5d_bar_date,
            outcome_5d_close,
            outcome_5d_directional_return,
            outcome_20d_bar_date,
            outcome_20d_close,
            outcome_20d_directional_return,
            latest_candidate_bar_date,
            latest_candidate_score,
            latest_monthly_triangle,
            latest_weekly_triangle,
            latest_daily_triangle,
            score_delta,
            signal_decay_flag,
            signal_decay_date,
            signal_decay_score,
            signal_decay_daily_triangle,
            whipsaw_after_promotion_flag,
            whipsaw_transition_date,
            whipsaw_transition_type,
            whipsaw_to_score,
            drift_status,
            rollback_recommendation,
            monitoring_status,
            explanation
        FROM hedge_fund.v_signal_promotion_post_execution_monitoring
        WHERE candidate_id = %(promotion_id)s
           OR acceptance_id::TEXT = %(promotion_id)s
           OR execution_id::TEXT = %(promotion_id)s
        ORDER BY
            CASE monitoring_status
                WHEN 'WARNING' THEN 0
                WHEN 'PENDING' THEN 1
                WHEN 'HEALTHY' THEN 2
                ELSE 3
            END,
            ABS(COALESCE(outcome_20d_directional_return, outcome_5d_directional_return, 0)) DESC,
            ticker
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"promotion_id": promotion_id, "limit": limit})
        rows = [
            {key: row[key] for key in PROMOTION_POST_EXECUTION_MONITORING_FIELDS}
            for row in cur.fetchall()
        ]
    warning_rows = [
        row for row in rows if row["monitoring_status"] == "WARNING"
    ]
    rollback_warning_rows = [
        row for row in rows if row["rollback_recommendation"] == "REVIEW_ROLLBACK_WARNING"
    ]
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "promotion_id": promotion_id,
        "summary": {
            "rows_checked": len(rows),
            "live_rows": sum(1 for row in rows if row["market_signal_live"]),
            "pending_rows": sum(1 for row in rows if row["monitoring_status"] == "PENDING"),
            "healthy_rows": sum(1 for row in rows if row["monitoring_status"] == "HEALTHY"),
            "warning_rows": len(warning_rows),
            "rollback_warning_rows": len(rollback_warning_rows),
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
            "adverse_20d_rows": sum(
                1
                for row in rows
                if row["outcome_20d_directional_return"] is not None
                and row["outcome_20d_directional_return"] < 0
            ),
        },
        "rows": rows,
    }


PROMOTION_POST_EXECUTION_ALERT_FIELDS = [
    "alert_id",
    "execution_id",
    "acceptance_id",
    "decision_record_id",
    "candidate_id",
    "market_signal_id",
    "ticker",
    "action",
    "candidate_bar_date",
    "alert_type",
    "severity",
    "alert_status",
    "alert_date",
    "metric_value",
    "rollback_recommendation",
    "monitoring_status",
    "drift_status",
    "evidence",
    "explanation",
    "operator_guidance",
]


def fetch_promotion_post_execution_alerts(
    conn: psycopg.Connection,
    *,
    promotion_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    sql = """
        SELECT
            alert_id,
            execution_id,
            acceptance_id,
            decision_record_id,
            candidate_id,
            market_signal_id,
            ticker,
            action,
            candidate_bar_date,
            alert_type,
            severity,
            alert_status,
            alert_date,
            metric_value,
            rollback_recommendation,
            monitoring_status,
            drift_status,
            evidence,
            explanation,
            operator_guidance
        FROM hedge_fund.v_signal_promotion_post_execution_alerts
        WHERE candidate_id = %(promotion_id)s
           OR acceptance_id::TEXT = %(promotion_id)s
           OR execution_id::TEXT = %(promotion_id)s
        ORDER BY
            CASE severity
                WHEN 'HIGH' THEN 0
                WHEN 'MEDIUM' THEN 1
                ELSE 2
            END,
            alert_date DESC NULLS LAST,
            ticker,
            alert_type
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"promotion_id": promotion_id, "limit": limit})
        rows = [
            {key: row[key] for key in PROMOTION_POST_EXECUTION_ALERT_FIELDS}
            for row in cur.fetchall()
        ]
    alert_counts = Counter(row["alert_type"] for row in rows)
    severity_counts = Counter(row["severity"] for row in rows)
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "promotion_id": promotion_id,
        "summary": {
            "total_alerts": len(rows),
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
        "alerts": rows,
    }


def execute_guarded_promotion(
    conn: psycopg.Connection,
    *,
    acceptance_id: str,
    operator_token_sha256: str,
    execution_rationale: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM hedge_fund.execute_guarded_signal_promotion(
                    %(acceptance_id)s::uuid,
                    %(operator_token_sha256)s,
                    %(execution_rationale)s,
                    %(idempotency_key)s
                )
                """,
                {
                    "acceptance_id": acceptance_id,
                    "operator_token_sha256": operator_token_sha256,
                    "execution_rationale": execution_rationale,
                    "idempotency_key": idempotency_key,
                },
            )
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise ValueError(str(exc).splitlines()[0]) from exc
    if row is None:
        raise RuntimeError("guarded promotion execution returned no row")
    return _promotion_execution_response(dict(row))


def rollback_promotion_execution(
    conn: psycopg.Connection,
    *,
    execution_id: str,
    operator_token_sha256: str,
    rollback_reason: str,
) -> dict[str, Any]:
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM hedge_fund.rollback_guarded_signal_promotion(
                    %(execution_id)s::uuid,
                    %(operator_token_sha256)s,
                    %(rollback_reason)s
                )
                """,
                {
                    "execution_id": execution_id,
                    "operator_token_sha256": operator_token_sha256,
                    "rollback_reason": rollback_reason,
                },
            )
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise ValueError(str(exc).splitlines()[0]) from exc
    if row is None:
        raise RuntimeError("guarded promotion rollback returned no row")
    return _promotion_execution_response(dict(row))


WATCHLIST_CANDIDATE_BASE_SQL = """
    WITH latest_scores AS (
        SELECT
            ticker,
            bar_date,
            parameter_set_name,
            monthly_state,
            weekly_state,
            daily_state,
            momentum_state,
            composite_score
        FROM (
            SELECT
                v.ticker,
                v.bar_date,
                v.parameter_set_name,
                v.monthly_state,
                v.weekly_state,
                v.daily_state,
                v.momentum_state,
                v.composite_score,
                ROW_NUMBER() OVER (
                    PARTITION BY v.ticker
                    ORDER BY v.bar_date DESC, v.computed_at DESC
                ) AS rn
            FROM hedge_fund.v_signal_scores_composite v
            JOIN hedge_fund.scoring_parameters p ON p.id = v.parameter_set_id
            WHERE {score_parameter_filter}
        ) ranked
        WHERE rn = 1
    ),
    latest_transition AS (
        SELECT DISTINCT ON (t.ticker)
            t.ticker,
            t.transition_type AS latest_transition_type,
            t.to_bar_date AS latest_transition_bar_date,
            t.notes AS latest_transition_notes
        FROM hedge_fund.signal_transitions t
        JOIN hedge_fund.scoring_parameters p ON p.id = t.parameter_set_id
        WHERE {transition_parameter_filter}
        ORDER BY t.ticker, t.to_bar_date DESC, t.detected_at DESC
    ),
    latest_watchlist AS (
        SELECT DISTINCT ON (ticker)
            ticker,
            sector,
            signal_count AS watchlist_signal_count,
            last_signal_at AS watchlist_last_signal_at
        FROM hedge_fund.watchlist
        ORDER BY ticker, last_signal_at DESC NULLS LAST, id DESC
    ),
    latest_market_signal AS (
        SELECT DISTINCT ON (ticker)
            ticker,
            action AS legacy_action,
            signal_type AS legacy_signal_type,
            confidence_score AS legacy_confidence_score,
            price_target AS legacy_price_target,
            extracted_at AS legacy_signal_at
        FROM hedge_fund.market_signals
        ORDER BY ticker, extracted_at DESC NULLS LAST, id DESC
    )
    SELECT
        s.ticker,
        s.bar_date,
        s.parameter_set_name,
        s.monthly_state,
        s.weekly_state,
        s.daily_state,
        s.momentum_state,
        s.composite_score,
        tr.latest_transition_type,
        tr.latest_transition_bar_date,
        tr.latest_transition_notes,
        wl.sector,
        wl.watchlist_signal_count,
        wl.watchlist_last_signal_at,
        ms.legacy_action,
        ms.legacy_signal_type,
        ms.legacy_confidence_score,
        ms.legacy_price_target,
        ms.legacy_signal_at
    FROM latest_scores s
    LEFT JOIN latest_transition tr ON tr.ticker = s.ticker
    LEFT JOIN latest_watchlist wl ON wl.ticker = s.ticker
    LEFT JOIN latest_market_signal ms ON ms.ticker = s.ticker
"""


def fetch_watchlist_candidates(
    conn: psycopg.Connection,
    *,
    limit: int,
    parameter_set: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    lane_specs = {
        "bullish_alignment": {
            "where": "s.composite_score >= 50",
            "order": "s.composite_score DESC, wl.watchlist_signal_count DESC NULLS LAST, s.ticker",
        },
        "risk_alignment": {
            "where": "s.composite_score <= -50",
            "order": "s.composite_score ASC, wl.watchlist_signal_count DESC NULLS LAST, s.ticker",
        },
        "reentry": {
            "where": """
                tr.latest_transition_type IN ('exit_to_reentry', 'breakout_bullish')
                AND s.composite_score >= 0
            """,
            "order": "tr.latest_transition_bar_date DESC NULLS LAST, s.composite_score DESC, s.ticker",
        },
        "mixed_timeframes": {
            "where": """
                s.monthly_state <> s.weekly_state
                OR s.weekly_state <> s.daily_state
            """,
            "order": "ABS(s.composite_score) DESC, wl.watchlist_signal_count DESC NULLS LAST, s.ticker",
        },
    }
    lanes: dict[str, list[dict[str, Any]]] = {}
    params: dict[str, Any] = {"limit": limit}
    if parameter_set:
        params["parameter_set"] = parameter_set
    base_sql = WATCHLIST_CANDIDATE_BASE_SQL.format(
        score_parameter_filter=_parameter_filter("p", parameter_set),
        transition_parameter_filter=_parameter_filter("p", parameter_set),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        for lane_id, spec in lane_specs.items():
            sql = f"""
                {base_sql}
                WHERE {spec["where"]}
                ORDER BY {spec["order"]}
                LIMIT %(limit)s
            """
            cur.execute(sql, params)
            lanes[lane_id] = [dict(row) for row in cur.fetchall()]
    return lanes


class PostgresSignalDataStore:
    def latest_scores(
        self,
        *,
        limit: int,
        ticker: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        parameter_set: str | None = None,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            return fetch_latest_scores(
                conn,
                limit=limit,
                ticker=ticker,
                min_score=min_score,
                max_score=max_score,
                parameter_set=parameter_set,
            )

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
        with connect() as conn:
            return fetch_recent_transitions(
                conn,
                limit=limit,
                ticker=ticker,
                transition_type=transition_type,
                since=since,
                lookback_days=lookback_days,
                parameter_set=parameter_set,
            )

    def watchlist_candidates(
        self,
        *,
        limit: int,
        parameter_set: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        with connect() as conn:
            return fetch_watchlist_candidates(conn, limit=limit, parameter_set=parameter_set)

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
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_daily_calibration(
                conn,
                since=since,
                until=until,
                ticker=ticker,
                parameter_set=parameter_set,
                top_tickers=top_tickers,
                event_window_days=event_window_days,
            ).as_json_dict()

    def promotion_gate(
        self,
        *,
        candidate_parameter_set: str,
        since: dt.date | None = None,
        until: dt.date | None = None,
        top_tickers: int = 20,
        event_window_days: int = 3,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_gate(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                since=since,
                until=until,
                top_tickers=top_tickers,
                event_window_days=event_window_days,
            )

    def shadow_review(
        self,
        *,
        candidate_parameter_set: str,
        lookback_days: int = 30,
        review_limit: int = 8,
        whipsaw_window_sessions: int = 5,
        outcome_horizon_sessions: int = 5,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_shadow_review(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                lookback_days=lookback_days,
                review_limit=review_limit,
                whipsaw_window_sessions=whipsaw_window_sessions,
                outcome_horizon_sessions=outcome_horizon_sessions,
            )

    def shadow_review_decision_records(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_shadow_review_decision_records(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                limit=limit,
            )

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
        with connect() as conn:
            return create_shadow_review_decision_record(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                decision=decision,
                reviewer=reviewer,
                rationale=rationale,
                rollback_criteria=rollback_criteria,
                reviewed_tickers=reviewed_tickers,
                notes=notes,
                lookback_days=lookback_days,
                review_limit=review_limit,
                whipsaw_window_sessions=whipsaw_window_sessions,
                outcome_horizon_sessions=outcome_horizon_sessions,
            )

    def promotion_dry_run(
        self,
        *,
        candidate_parameter_set: str,
        decision_id: str | None = None,
        limit: int = 100,
        min_abs_score: int = 50,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_dry_run(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                decision_id=decision_id,
                limit=limit,
                min_abs_score=min_abs_score,
            )

    def promotion_dry_run_verification(
        self,
        *,
        candidate_parameter_set: str,
        production_parameter_set: str = PRODUCTION_PARAMETER_SET,
        decision_id: str | None = None,
        limit: int = 500,
        min_abs_score: int = 50,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_dry_run_verification(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                production_parameter_set=production_parameter_set,
                decision_id=decision_id,
                limit=limit,
                min_abs_score=min_abs_score,
            )

    def promotion_dry_run_acceptances(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_dry_run_acceptances(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                limit=limit,
            )

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
        with connect() as conn:
            return create_promotion_dry_run_acceptance(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                accepted_by=accepted_by,
                acceptance_rationale=acceptance_rationale,
                decision_id=decision_id,
                limit=limit,
                min_abs_score=min_abs_score,
            )

    def promotion_executions(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_executions(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                limit=limit,
            )

    def promotion_rollback_drills(
        self,
        *,
        candidate_parameter_set: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_rollback_drills(
                conn,
                candidate_parameter_set=candidate_parameter_set,
                limit=limit,
            )

    def promotion_lifecycle_timeline(
        self,
        *,
        promotion_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_lifecycle_timeline(
                conn,
                promotion_id=promotion_id,
                limit=limit,
            )

    def promotion_reconciliation(
        self,
        *,
        promotion_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_reconciliation(
                conn,
                promotion_id=promotion_id,
                limit=limit,
            )

    def promotion_post_execution_monitoring(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_post_execution_monitoring(
                conn,
                promotion_id=promotion_id,
                limit=limit,
            )

    def promotion_post_execution_alerts(
        self,
        *,
        promotion_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_promotion_post_execution_alerts(
                conn,
                promotion_id=promotion_id,
                limit=limit,
            )

    def execute_guarded_promotion(
        self,
        *,
        acceptance_id: str,
        operator_token_sha256: str,
        execution_rationale: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with connect() as conn:
            return execute_guarded_promotion(
                conn,
                acceptance_id=acceptance_id,
                operator_token_sha256=operator_token_sha256,
                execution_rationale=execution_rationale,
                idempotency_key=idempotency_key,
            )

    def rollback_promotion_execution(
        self,
        *,
        execution_id: str,
        operator_token_sha256: str,
        rollback_reason: str,
    ) -> dict[str, Any]:
        with connect() as conn:
            return rollback_promotion_execution(
                conn,
                execution_id=execution_id,
                operator_token_sha256=operator_token_sha256,
                rollback_reason=rollback_reason,
            )

    def symbol_chart(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
    ) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_symbol_chart(
                conn,
                ticker=ticker,
                sessions=sessions,
                as_of=as_of,
                parameter_set=parameter_set,
            )

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
        with connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            return fetch_symbol_whipsaw_risk(
                conn,
                ticker=ticker,
                sessions=sessions,
                as_of=as_of,
                parameter_set=parameter_set,
                whipsaw_window_sessions=whipsaw_window_sessions,
                outcome_horizon_sessions=outcome_horizon_sessions,
            )
