"""Database read model for daily MarketClub / Dochia calibration."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.signals.calibration import (
    CalibrationObservation,
    CalibrationWeights,
    DailyCalibrationResult,
    evaluate_daily_calibration,
)
from app.signals.db_preview import eod_row_to_bar
from app.signals.trade_triangles import EodBar


def _fetch_parameter_set(conn: psycopg.Connection, name: str | None) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        if name:
            cur.execute(
                """
                SELECT id, name, weight_monthly, weight_weekly, weight_daily, weight_momentum
                FROM hedge_fund.scoring_parameters
                WHERE name = %s
                """,
                (name,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, weight_monthly, weight_weekly, weight_daily, weight_momentum
                FROM hedge_fund.scoring_parameters
                WHERE is_production = TRUE
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        row = cur.fetchone()
    if not row:
        target = name or "production"
        raise RuntimeError(f"scoring parameter set not found: {target}")
    return dict(row)


def _fetch_observations(
    conn: psycopg.Connection,
    *,
    since: dt.date | None,
    until: dt.date | None,
    ticker: str | None,
) -> list[CalibrationObservation]:
    conditions = ["timeframe = 'daily'"]
    params: dict[str, Any] = {}
    if since is not None:
        conditions.append("trading_day >= %(since)s")
        params["since"] = since
    if until is not None:
        conditions.append("trading_day <= %(until)s")
        params["until"] = until
    if ticker:
        conditions.append("ticker = %(ticker)s")
        params["ticker"] = ticker.upper()

    where_clause = " AND ".join(conditions)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT ticker, trading_day, triangle_color, score
            FROM hedge_fund.market_club_observations
            WHERE {where_clause}
            ORDER BY ticker, trading_day, id
            """,
            params,
        )
        return [
            CalibrationObservation(
                ticker=str(row["ticker"]),
                trading_day=row["trading_day"],
                triangle_color=str(row["triangle_color"]),
                score=int(row["score"]),
            )
            for row in cur.fetchall()
        ]


def _fetch_bars_by_ticker(
    conn: psycopg.Connection,
    *,
    tickers: list[str],
    until: dt.date | None,
) -> dict[str, list[EodBar]]:
    if not tickers:
        return {}
    params: dict[str, Any] = {"tickers": tickers, "until": until}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT ticker, bar_date, open, high, low, close, volume
            FROM hedge_fund.eod_bars
            WHERE ticker = ANY(%(tickers)s)
              AND (%(until)s::date IS NULL OR bar_date <= %(until)s::date)
            ORDER BY ticker, bar_date
            """,
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]

    bars_by_ticker: dict[str, list[EodBar]] = {ticker: [] for ticker in tickers}
    for row in rows:
        bars_by_ticker[str(row["ticker"])].append(eod_row_to_bar(row))
    return bars_by_ticker


def fetch_daily_calibration(
    conn: psycopg.Connection,
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
    ticker: str | None = None,
    parameter_set: str | None = None,
    top_tickers: int = 20,
) -> DailyCalibrationResult:
    parameter = _fetch_parameter_set(conn, parameter_set)
    observations = _fetch_observations(conn, since=since, until=until, ticker=ticker)
    tickers = sorted({observation.ticker for observation in observations})
    bars_by_ticker = _fetch_bars_by_ticker(conn, tickers=tickers, until=until)
    weights = CalibrationWeights(
        monthly=int(parameter["weight_monthly"]),
        weekly=int(parameter["weight_weekly"]),
        daily=int(parameter["weight_daily"]),
        momentum=int(parameter["weight_momentum"]),
    )
    return evaluate_daily_calibration(
        observations,
        bars_by_ticker,
        parameter_set_name=str(parameter["name"]),
        weights=weights,
        since=since,
        until=until,
        top_ticker_count=top_tickers,
    )
