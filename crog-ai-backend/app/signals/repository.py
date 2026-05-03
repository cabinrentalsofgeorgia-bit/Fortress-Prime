"""Read models for MarketClub / Dochia app-facing signal endpoints."""

from __future__ import annotations

import datetime as dt
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
