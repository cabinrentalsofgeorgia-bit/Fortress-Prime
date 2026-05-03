"""Chart data read model for MarketClub / Dochia signal overlays."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.signals.db_preview import eod_row_to_bar
from app.signals.trade_triangles import (
    LOOKBACK_SESSIONS,
    EodBar,
    TriangleEvent,
    TriangleTimeframe,
    detect_triangle_events,
)

CHART_LOOKBACK_BUFFER = max(LOOKBACK_SESSIONS.values())


def _channel_for(
    bars: list[EodBar],
    index: int,
    timeframe: TriangleTimeframe,
) -> tuple[Decimal | None, Decimal | None]:
    lookback = LOOKBACK_SESSIONS[timeframe]
    if index < lookback:
        return None, None
    previous = bars[index - lookback : index]
    return (
        max(bar.high for bar in previous),
        min(bar.low for bar in previous),
    )


def _event_to_dict(event: TriangleEvent) -> dict[str, Any]:
    return {
        "ticker": event.ticker,
        "timeframe": event.timeframe.value,
        "state": event.state.value,
        "bar_date": event.bar_date,
        "trigger_price": event.trigger_price,
        "channel_high": event.channel_high,
        "channel_low": event.channel_low,
        "lookback_sessions": event.lookback_sessions,
        "reason": event.reason,
    }


def build_symbol_chart(
    *,
    ticker: str,
    bars: list[EodBar],
    sessions: int,
) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda bar: bar.bar_date)
    visible_bars = ordered[-sessions:]
    if not visible_bars:
        return {"ticker": ticker.upper(), "sessions": sessions, "bars": [], "events": []}

    first_visible_date = visible_bars[0].bar_date
    index_by_date = {bar.bar_date: index for index, bar in enumerate(ordered)}
    chart_bars: list[dict[str, Any]] = []
    for bar in visible_bars:
        index = index_by_date[bar.bar_date]
        daily_high, daily_low = _channel_for(ordered, index, TriangleTimeframe.DAILY)
        weekly_high, weekly_low = _channel_for(ordered, index, TriangleTimeframe.WEEKLY)
        monthly_high, monthly_low = _channel_for(ordered, index, TriangleTimeframe.MONTHLY)
        chart_bars.append(
            {
                "ticker": bar.ticker,
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "daily_channel_high": daily_high,
                "daily_channel_low": daily_low,
                "weekly_channel_high": weekly_high,
                "weekly_channel_low": weekly_low,
                "monthly_channel_high": monthly_high,
                "monthly_channel_low": monthly_low,
            }
        )

    events = [
        _event_to_dict(event)
        for timeframe in TriangleTimeframe
        for event in detect_triangle_events(ordered, timeframe)
        if event.bar_date >= first_visible_date
    ]
    events.sort(key=lambda item: (item["bar_date"], item["timeframe"]))
    return {
        "ticker": ticker.upper(),
        "sessions": len(visible_bars),
        "bars": chart_bars,
        "events": events,
    }


def fetch_symbol_chart(
    conn: psycopg.Connection,
    *,
    ticker: str,
    sessions: int,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    normalized = ticker.upper()
    fetch_limit = sessions + CHART_LOOKBACK_BUFFER
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
    return build_symbol_chart(ticker=normalized, bars=bars, sessions=sessions)
