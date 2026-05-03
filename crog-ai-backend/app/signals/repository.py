"""Read models for MarketClub / Dochia app-facing signal endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from app.database import connect
from app.signals.calibration_repository import fetch_daily_calibration
from app.signals.chart_repository import fetch_symbol_chart


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

    def symbol_chart(
        self,
        *,
        ticker: str,
        sessions: int,
        as_of: dt.date | None = None,
        parameter_set: str | None = None,
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
