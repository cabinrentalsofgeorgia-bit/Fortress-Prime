"""Deterministic Trade Triangle style signal engine.

This is the first Dochia layer: an explainable channel-break approximation
of MarketClub's daily, weekly, and monthly Trade Triangles using EOD bars.
It does not claim exact INO replication. Calibration against the historical
MarketClub corpus belongs in the next layer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class TriangleState(StrEnum):
    GREEN = "green"
    RED = "red"
    NEUTRAL = "neutral"

    @property
    def numeric(self) -> int:
        if self is TriangleState.GREEN:
            return 1
        if self is TriangleState.RED:
            return -1
        return 0


class TriangleTimeframe(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


LOOKBACK_SESSIONS: dict[TriangleTimeframe, int] = {
    TriangleTimeframe.DAILY: 3,
    TriangleTimeframe.WEEKLY: 15,
    TriangleTimeframe.MONTHLY: 63,
}


@dataclass(frozen=True, slots=True)
class EodBar:
    ticker: str
    bar_date: dt.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None


@dataclass(frozen=True, slots=True)
class TriangleEvent:
    ticker: str
    timeframe: TriangleTimeframe
    state: TriangleState
    bar_date: dt.date
    trigger_price: Decimal
    channel_high: Decimal
    channel_low: Decimal
    lookback_sessions: int
    reason: str


@dataclass(frozen=True, slots=True)
class TriangleSnapshot:
    ticker: str
    bar_date: dt.date
    daily_state: TriangleState
    weekly_state: TriangleState
    monthly_state: TriangleState
    daily_channel_high: Decimal | None
    daily_channel_low: Decimal | None
    weekly_channel_high: Decimal | None
    weekly_channel_low: Decimal | None
    monthly_channel_high: Decimal | None
    monthly_channel_low: Decimal | None
    events: tuple[TriangleEvent, ...]

    @property
    def state_tuple(self) -> tuple[int, int, int]:
        return (
            self.monthly_state.numeric,
            self.weekly_state.numeric,
            self.daily_state.numeric,
        )

    def composite_score(
        self,
        *,
        monthly_weight: int = 40,
        weekly_weight: int = 25,
        daily_weight: int = 15,
        momentum_state: int = 0,
        momentum_weight: int = 20,
    ) -> int:
        """Return the schema-compatible -100..100 composite score."""
        return (
            self.monthly_state.numeric * monthly_weight
            + self.weekly_state.numeric * weekly_weight
            + self.daily_state.numeric * daily_weight
            + momentum_state * momentum_weight
        )


def _sorted_bars(bars: Iterable[EodBar]) -> list[EodBar]:
    ordered = sorted(bars, key=lambda bar: (bar.ticker, bar.bar_date))
    if not ordered:
        return []
    tickers = {bar.ticker for bar in ordered}
    if len(tickers) != 1:
        raise ValueError("bars must contain exactly one ticker")
    return ordered


def _channel(reference_bars: Sequence[EodBar]) -> tuple[Decimal, Decimal]:
    return (
        max(bar.high for bar in reference_bars),
        min(bar.low for bar in reference_bars),
    )


def detect_triangle_events(
    bars: Iterable[EodBar],
    timeframe: TriangleTimeframe,
) -> tuple[TriangleEvent, ...]:
    """Detect state-changing channel breaks for one timeframe.

    The state changes when the current close breaks above the prior channel
    high or below the prior channel low. The prior channel excludes the current
    bar, preventing look-ahead bias.
    """
    ordered = _sorted_bars(bars)
    lookback = LOOKBACK_SESSIONS[timeframe]
    if len(ordered) <= lookback:
        return ()

    events: list[TriangleEvent] = []
    current_state = TriangleState.NEUTRAL
    ticker = ordered[0].ticker

    for index in range(lookback, len(ordered)):
        current = ordered[index]
        previous = ordered[index - lookback : index]
        channel_high, channel_low = _channel(previous)

        next_state = TriangleState.NEUTRAL
        reason = ""
        if current.close > channel_high:
            next_state = TriangleState.GREEN
            reason = f"close {current.close} broke above prior {lookback}-session high {channel_high}"
        elif current.close < channel_low:
            next_state = TriangleState.RED
            reason = f"close {current.close} broke below prior {lookback}-session low {channel_low}"

        if next_state is TriangleState.NEUTRAL or next_state is current_state:
            continue

        event = TriangleEvent(
            ticker=ticker,
            timeframe=timeframe,
            state=next_state,
            bar_date=current.bar_date,
            trigger_price=current.close,
            channel_high=channel_high,
            channel_low=channel_low,
            lookback_sessions=lookback,
            reason=reason,
        )
        events.append(event)
        current_state = next_state

    return tuple(events)


def latest_triangle_snapshot(
    bars: Iterable[EodBar],
    *,
    as_of: dt.date | None = None,
) -> TriangleSnapshot:
    """Compute latest daily, weekly, and monthly states for one ticker."""
    ordered = _sorted_bars(bars)
    if as_of is not None:
        ordered = [bar for bar in ordered if bar.bar_date <= as_of]
    if not ordered:
        raise ValueError("at least one bar is required")

    events_by_timeframe = {
        timeframe: detect_triangle_events(ordered, timeframe)
        for timeframe in TriangleTimeframe
    }
    all_events = tuple(
        sorted(
            (event for events in events_by_timeframe.values() for event in events),
            key=lambda event: (event.bar_date, event.timeframe.value),
        )
    )

    def _latest_state(timeframe: TriangleTimeframe) -> TriangleState:
        events = events_by_timeframe[timeframe]
        return events[-1].state if events else TriangleState.NEUTRAL

    def _latest_channel(timeframe: TriangleTimeframe) -> tuple[Decimal | None, Decimal | None]:
        lookback = LOOKBACK_SESSIONS[timeframe]
        if len(ordered) <= lookback:
            return None, None
        return _channel(ordered[-lookback - 1 : -1])

    daily_high, daily_low = _latest_channel(TriangleTimeframe.DAILY)
    weekly_high, weekly_low = _latest_channel(TriangleTimeframe.WEEKLY)
    monthly_high, monthly_low = _latest_channel(TriangleTimeframe.MONTHLY)

    return TriangleSnapshot(
        ticker=ordered[0].ticker,
        bar_date=ordered[-1].bar_date,
        daily_state=_latest_state(TriangleTimeframe.DAILY),
        weekly_state=_latest_state(TriangleTimeframe.WEEKLY),
        monthly_state=_latest_state(TriangleTimeframe.MONTHLY),
        daily_channel_high=daily_high,
        daily_channel_low=daily_low,
        weekly_channel_high=weekly_high,
        weekly_channel_low=weekly_low,
        monthly_channel_high=monthly_high,
        monthly_channel_low=monthly_low,
        events=all_events,
    )
