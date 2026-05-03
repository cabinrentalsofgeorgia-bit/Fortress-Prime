"""Whipsaw and forward-return read model for app-facing signal review."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.signals.chart_repository import (
    PRODUCTION_PARAMETER_SET,
    daily_trigger_mode_for_parameter_set,
)
from app.signals.db_preview import eod_row_to_bar
from app.signals.outcome_review import SignalEvent, summarize_forward_returns
from app.signals.trade_triangles import (
    EodBar,
    TriangleTimeframe,
    detect_triangle_events,
)

DAILY_LOOKBACK_BUFFER = 3


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _state_label(value: int) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "neutral"


def _directional_return(
    event: SignalEvent,
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    horizon_sessions: int,
) -> float | None:
    bars = sorted(bars_by_ticker.get(event.ticker, []), key=lambda bar: bar.bar_date)
    future_index = event.index + horizon_sessions
    if future_index >= len(bars):
        return None
    entry_close = bars[event.index].close
    future_close = bars[future_index].close
    if entry_close == 0:
        return None
    return float((future_close - entry_close) / entry_close) * event.state


def _risk_score(
    *,
    whipsaw_count: int,
    whipsaw_rate: float | None,
    average_directional_return: float | None,
) -> int:
    rate_score = int(round((whipsaw_rate or 0) * 100))
    count_score = min(100, whipsaw_count * 20)
    return_drag = 15 if average_directional_return is not None and average_directional_return < 0 else 0
    return min(100, max(rate_score, count_score) + return_drag)


def _risk_level(
    *,
    event_count: int,
    whipsaw_count: int,
    whipsaw_rate: float | None,
    risk_score: int,
) -> str:
    if event_count < 2:
        return "quiet"
    if whipsaw_count >= 3 and (whipsaw_rate or 0) >= 0.35:
        return "high"
    if whipsaw_count >= 2 and (whipsaw_rate or 0) >= 0.75:
        return "high"
    if risk_score >= 45 or whipsaw_count >= 2 or (whipsaw_rate or 0) >= 0.25:
        return "elevated"
    return "quiet"


def _signal_events_from_bars(
    bars: list[EodBar],
    *,
    parameter_set: str | None,
    first_visible_date: dt.date,
) -> list[SignalEvent]:
    ordered = sorted(bars, key=lambda bar: bar.bar_date)
    index_by_date = {bar.bar_date: index for index, bar in enumerate(ordered)}
    daily_trigger_mode = daily_trigger_mode_for_parameter_set(parameter_set)
    events = detect_triangle_events(
        ordered,
        TriangleTimeframe.DAILY,
        trigger_mode=daily_trigger_mode,
    )
    return [
        SignalEvent(
            ticker=event.ticker,
            event_date=event.bar_date,
            index=index_by_date[event.bar_date],
            state=event.state.numeric,
        )
        for event in events
        if event.bar_date >= first_visible_date
    ]


def build_symbol_whipsaw_risk(
    *,
    ticker: str,
    bars: list[EodBar],
    sessions: int,
    parameter_set: str | None = None,
    whipsaw_window_sessions: int = 5,
    outcome_horizon_sessions: int = 5,
) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda bar: bar.bar_date)
    parameter_set_name = parameter_set or PRODUCTION_PARAMETER_SET
    daily_trigger_mode = daily_trigger_mode_for_parameter_set(parameter_set)
    visible_bars = ordered[-sessions:]
    if not visible_bars:
        return {
            "ticker": ticker.upper(),
            "parameter_set_name": parameter_set_name,
            "daily_trigger_mode": daily_trigger_mode.value,
            "sessions": sessions,
            "as_of": None,
            "whipsaw_window_sessions": whipsaw_window_sessions,
            "outcome_horizon_sessions": outcome_horizon_sessions,
            "event_count": 0,
            "whipsaw_count": 0,
            "whipsaw_rate": None,
            "latest_whipsaw_date": None,
            "risk_score": 0,
            "risk_level": "quiet",
            "outcome": summarize_forward_returns([], {}, horizons=[outcome_horizon_sessions])[
                0
            ].as_json_dict(),
            "recent_events": [],
        }

    bars_by_ticker = {ticker.upper(): ordered}
    events = _signal_events_from_bars(
        ordered,
        parameter_set=parameter_set,
        first_visible_date=visible_bars[0].bar_date,
    )

    whipsaw_dates: list[dt.date] = []
    recent_events: list[dict[str, Any]] = []
    previous: SignalEvent | None = None
    for event in events:
        sessions_since_previous = event.index - previous.index if previous else None
        is_whipsaw = (
            previous is not None
            and event.state != previous.state
            and sessions_since_previous is not None
            and sessions_since_previous <= whipsaw_window_sessions
        )
        if is_whipsaw:
            whipsaw_dates.append(event.event_date)
        recent_events.append(
            {
                "event_date": event.event_date,
                "state": _state_label(event.state),
                "sessions_since_previous": sessions_since_previous,
                "is_whipsaw": is_whipsaw,
                "directional_return": _directional_return(
                    event,
                    bars_by_ticker,
                    horizon_sessions=outcome_horizon_sessions,
                ),
            }
        )
        previous = event

    outcome = summarize_forward_returns(
        events,
        bars_by_ticker,
        horizons=[outcome_horizon_sessions],
    )[0]
    whipsaw_count = len(whipsaw_dates)
    whipsaw_rate = _safe_rate(whipsaw_count, max(len(events) - 1, 0))
    risk_score = _risk_score(
        whipsaw_count=whipsaw_count,
        whipsaw_rate=whipsaw_rate,
        average_directional_return=outcome.average_directional_return,
    )
    return {
        "ticker": ticker.upper(),
        "parameter_set_name": parameter_set_name,
        "daily_trigger_mode": daily_trigger_mode.value,
        "sessions": len(visible_bars),
        "as_of": visible_bars[-1].bar_date,
        "whipsaw_window_sessions": whipsaw_window_sessions,
        "outcome_horizon_sessions": outcome_horizon_sessions,
        "event_count": len(events),
        "whipsaw_count": whipsaw_count,
        "whipsaw_rate": whipsaw_rate,
        "latest_whipsaw_date": max(whipsaw_dates) if whipsaw_dates else None,
        "risk_score": risk_score,
        "risk_level": _risk_level(
            event_count=len(events),
            whipsaw_count=whipsaw_count,
            whipsaw_rate=whipsaw_rate,
            risk_score=risk_score,
        ),
        "outcome": outcome.as_json_dict(),
        "recent_events": list(reversed(recent_events[-8:])),
    }


def fetch_symbol_whipsaw_risk(
    conn: psycopg.Connection,
    *,
    ticker: str,
    sessions: int,
    as_of: dt.date | None = None,
    parameter_set: str | None = None,
    whipsaw_window_sessions: int = 5,
    outcome_horizon_sessions: int = 5,
) -> dict[str, Any]:
    normalized = ticker.upper()
    fetch_limit = sessions + DAILY_LOOKBACK_BUFFER
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT ticker, bar_date, open, high, low, close, volume
            FROM (
                SELECT ticker, bar_date, open, high, low, close, volume
                FROM hedge_fund.eod_bars
                WHERE ticker = %(ticker)s
                  AND (%(as_of)s::date IS NULL OR bar_date <= %(as_of)s::date)
                ORDER BY bar_date DESC
                LIMIT %(limit)s
            ) latest
            ORDER BY bar_date
            """,
            {"ticker": normalized, "as_of": as_of, "limit": fetch_limit},
        )
        bars = [eod_row_to_bar(dict(row)) for row in cur.fetchall()]
    return build_symbol_whipsaw_risk(
        ticker=normalized,
        bars=bars,
        sessions=sessions,
        parameter_set=parameter_set,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
    )
