"""Forward-return and whipsaw review helpers for Dochia signal candidates."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import asdict, dataclass
from statistics import median

from app.signals.calibration_sweep import DailyEventHistory
from app.signals.trade_triangles import EodBar


@dataclass(frozen=True, slots=True)
class SignalEvent:
    ticker: str
    event_date: dt.date
    index: int
    state: int


@dataclass(frozen=True, slots=True)
class ReturnOutcomeSummary:
    horizon_sessions: int
    evaluated_events: int
    win_count: int
    win_rate: float | None
    average_directional_return: float | None
    median_directional_return: float | None
    p25_directional_return: float | None
    p75_directional_return: float | None

    def as_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TickerWhipsawOutcome:
    ticker: str
    event_count: int
    whipsaw_count: int
    whipsaw_rate: float
    evaluated_horizon_events: int
    average_directional_return: float | None
    latest_whipsaw_date: str | None

    def as_json_dict(self) -> dict[str, object]:
        return asdict(self)


def _ordered_bars(bars: list[EodBar]) -> list[EodBar]:
    return sorted(bars, key=lambda bar: (bar.ticker, bar.bar_date))


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def events_from_histories(
    histories: dict[str, DailyEventHistory],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    for ticker, history in histories.items():
        bars = _ordered_bars(bars_by_ticker.get(ticker, []))
        index_by_date = {bar.bar_date: index for index, bar in enumerate(bars)}
        for event_date, state in sorted(history.event_by_date.items()):
            if since is not None and event_date < since:
                continue
            if until is not None and event_date > until:
                continue
            index = index_by_date.get(event_date)
            if index is None:
                continue
            events.append(
                SignalEvent(
                    ticker=ticker,
                    event_date=event_date,
                    index=index,
                    state=state,
                )
            )
    return sorted(events, key=lambda event: (event.ticker, event.index))


def _directional_return(
    event: SignalEvent,
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    horizon_sessions: int,
) -> float | None:
    bars = _ordered_bars(bars_by_ticker.get(event.ticker, []))
    future_index = event.index + horizon_sessions
    if future_index >= len(bars):
        return None
    entry_close = bars[event.index].close
    future_close = bars[future_index].close
    if entry_close == 0:
        return None
    raw_return = (future_close - entry_close) / entry_close
    return float(raw_return) * event.state


def summarize_forward_returns(
    events: list[SignalEvent],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    horizons: list[int],
) -> list[ReturnOutcomeSummary]:
    summaries: list[ReturnOutcomeSummary] = []
    for horizon in horizons:
        returns = [
            value
            for event in events
            if (
                value := _directional_return(
                    event,
                    bars_by_ticker,
                    horizon_sessions=horizon,
                )
            )
            is not None
        ]
        win_count = sum(value > 0 for value in returns)
        summaries.append(
            ReturnOutcomeSummary(
                horizon_sessions=horizon,
                evaluated_events=len(returns),
                win_count=win_count,
                win_rate=_safe_rate(win_count, len(returns)),
                average_directional_return=(
                    sum(returns) / len(returns) if returns else None
                ),
                median_directional_return=median(returns) if returns else None,
                p25_directional_return=_percentile(returns, 0.25),
                p75_directional_return=_percentile(returns, 0.75),
            )
        )
    return summaries


def build_ticker_whipsaw_outcomes(
    events: list[SignalEvent],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    whipsaw_window_sessions: int,
    outcome_horizon_sessions: int,
    top: int,
) -> list[TickerWhipsawOutcome]:
    grouped: dict[str, list[SignalEvent]] = defaultdict(list)
    for event in events:
        grouped[event.ticker].append(event)

    outcomes: list[TickerWhipsawOutcome] = []
    for ticker, ticker_events in grouped.items():
        ordered = sorted(ticker_events, key=lambda event: event.index)
        whipsaw_dates: list[dt.date] = []
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.state == previous.state:
                continue
            if current.index - previous.index <= whipsaw_window_sessions:
                whipsaw_dates.append(current.event_date)
        if not whipsaw_dates:
            continue

        returns = [
            value
            for event in ordered
            if (
                value := _directional_return(
                    event,
                    bars_by_ticker,
                    horizon_sessions=outcome_horizon_sessions,
                )
            )
            is not None
        ]
        outcomes.append(
            TickerWhipsawOutcome(
                ticker=ticker,
                event_count=len(ordered),
                whipsaw_count=len(whipsaw_dates),
                whipsaw_rate=len(whipsaw_dates) / max(len(ordered) - 1, 1),
                evaluated_horizon_events=len(returns),
                average_directional_return=(
                    sum(returns) / len(returns) if returns else None
                ),
                latest_whipsaw_date=max(whipsaw_dates).isoformat(),
            )
        )

    outcomes.sort(
        key=lambda item: (
            item.whipsaw_count,
            item.whipsaw_rate,
            item.event_count,
            item.ticker,
        ),
        reverse=True,
    )
    return outcomes[:top]
