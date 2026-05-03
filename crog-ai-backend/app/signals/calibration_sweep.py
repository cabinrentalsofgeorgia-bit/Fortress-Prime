"""Parameter sweeps for daily MarketClub alert-event calibration."""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Literal

from app.signals.calibration import CalibrationObservation, normalize_triangle_color
from app.signals.trade_triangles import EodBar, TriangleState

DailyTriggerMode = Literal["close", "range"]


@dataclass(frozen=True, slots=True)
class DailySweepCandidate:
    lookback_sessions: int
    trigger_mode: DailyTriggerMode


@dataclass(frozen=True, slots=True)
class DailyEventHistory:
    ticker: str
    dates: tuple[dt.date, ...]
    state_by_date: dict[dt.date, int]
    event_by_date: dict[dt.date, int]
    event_dates_by_state: dict[int, tuple[dt.date, ...]]

    def state_as_of(self, trading_day: dt.date) -> int | None:
        index = bisect_right(self.dates, trading_day) - 1
        if index < 0:
            return None
        return self.state_by_date[self.dates[index]]

    def event_on(self, trading_day: dt.date) -> int | None:
        return self.event_by_date.get(trading_day)

    def has_event_within(self, *, trading_day: dt.date, state: int, window_days: int) -> bool:
        for event_date in self.event_dates_by_state.get(state, ()):
            if abs((event_date - trading_day).days) <= window_days:
                return True
        return False


@dataclass(frozen=True, slots=True)
class DailySweepResult:
    lookback_sessions: int
    trigger_mode: DailyTriggerMode
    total_observations: int
    covered_observations: int
    generated_events: int
    carried_state_matches: int
    exact_event_matches: int
    window_event_matches: int
    opposite_event_observations: int
    no_event_observations: int
    carried_state_accuracy: float | None
    exact_event_recall: float | None
    exact_event_precision: float | None
    exact_event_f1: float | None
    window_event_recall: float | None

    def as_json_dict(self) -> dict[str, object]:
        return asdict(self)


def _channel(reference_bars: list[EodBar]) -> tuple[Decimal, Decimal]:
    return (
        max(bar.high for bar in reference_bars),
        min(bar.low for bar in reference_bars),
    )


def _range_break_state(bar: EodBar, channel_high: Decimal, channel_low: Decimal) -> int:
    broke_high = bar.high > channel_high
    broke_low = bar.low < channel_low
    if broke_high and broke_low:
        return TriangleState.GREEN.numeric if bar.close >= bar.open else TriangleState.RED.numeric
    if broke_high:
        return TriangleState.GREEN.numeric
    if broke_low:
        return TriangleState.RED.numeric
    return TriangleState.NEUTRAL.numeric


def _close_break_state(bar: EodBar, channel_high: Decimal, channel_low: Decimal) -> int:
    if bar.close > channel_high:
        return TriangleState.GREEN.numeric
    if bar.close < channel_low:
        return TriangleState.RED.numeric
    return TriangleState.NEUTRAL.numeric


def generated_daily_event_history(
    bars: list[EodBar],
    *,
    lookback_sessions: int,
    trigger_mode: DailyTriggerMode,
) -> DailyEventHistory | None:
    ordered = sorted(bars, key=lambda bar: (bar.ticker, bar.bar_date))
    if not ordered:
        return None
    ticker = ordered[0].ticker
    if any(bar.ticker != ticker for bar in ordered):
        raise ValueError("bars must contain exactly one ticker")

    current_state = TriangleState.NEUTRAL.numeric
    state_by_date: dict[dt.date, int] = {}
    event_by_date: dict[dt.date, int] = {}
    event_dates_by_state: dict[int, list[dt.date]] = defaultdict(list)
    dates: list[dt.date] = []

    for index, bar in enumerate(ordered):
        if index >= lookback_sessions:
            channel_high, channel_low = _channel(ordered[index - lookback_sessions : index])
            next_state = (
                _close_break_state(bar, channel_high, channel_low)
                if trigger_mode == "close"
                else _range_break_state(bar, channel_high, channel_low)
            )
            if next_state != TriangleState.NEUTRAL.numeric and next_state != current_state:
                current_state = next_state
                event_by_date[bar.bar_date] = next_state
                event_dates_by_state[next_state].append(bar.bar_date)

        state_by_date[bar.bar_date] = current_state
        dates.append(bar.bar_date)

    return DailyEventHistory(
        ticker=ticker,
        dates=tuple(dates),
        state_by_date=state_by_date,
        event_by_date=event_by_date,
        event_dates_by_state={
            state: tuple(sorted(event_dates)) for state, event_dates in event_dates_by_state.items()
        },
    )


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def evaluate_daily_sweep_candidate(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    candidate: DailySweepCandidate,
    event_window_days: int = 3,
) -> DailySweepResult:
    histories = {
        ticker: history
        for ticker, bars in bars_by_ticker.items()
        if (
            history := generated_daily_event_history(
                bars,
                lookback_sessions=candidate.lookback_sessions,
                trigger_mode=candidate.trigger_mode,
            )
        )
        is not None
    }
    if observations:
        since = min(observation.trading_day for observation in observations)
        until = max(observation.trading_day for observation in observations)
    else:
        since = until = None

    covered = 0
    state_matches = 0
    exact_matches = 0
    window_matches = 0
    opposite_events = 0
    no_events = 0
    generated_events = 0
    matched_generated_events: set[tuple[str, dt.date]] = set()

    for history in histories.values():
        for event_date in history.event_by_date:
            if since is not None and event_date < since:
                continue
            if until is not None and event_date > until:
                continue
            generated_events += 1

    for observation in observations:
        actual = normalize_triangle_color(observation.triangle_color)
        actual_state = TriangleState.GREEN.numeric if actual == "green" else TriangleState.RED.numeric
        history = histories.get(observation.ticker)
        if history is None:
            continue

        state = history.state_as_of(observation.trading_day)
        if state is None:
            continue
        covered += 1
        if state == actual_state:
            state_matches += 1

        event = history.event_on(observation.trading_day)
        if event is None:
            no_events += 1
        elif event == actual_state:
            exact_matches += 1
            matched_generated_events.add((observation.ticker, observation.trading_day))
        else:
            opposite_events += 1

        if history.has_event_within(
            trading_day=observation.trading_day,
            state=actual_state,
            window_days=event_window_days,
        ):
            window_matches += 1

    recall = _safe_rate(exact_matches, covered)
    precision = _safe_rate(len(matched_generated_events), generated_events)
    return DailySweepResult(
        lookback_sessions=candidate.lookback_sessions,
        trigger_mode=candidate.trigger_mode,
        total_observations=len(observations),
        covered_observations=covered,
        generated_events=generated_events,
        carried_state_matches=state_matches,
        exact_event_matches=exact_matches,
        window_event_matches=window_matches,
        opposite_event_observations=opposite_events,
        no_event_observations=no_events,
        carried_state_accuracy=_safe_rate(state_matches, covered),
        exact_event_recall=recall,
        exact_event_precision=precision,
        exact_event_f1=_f1(precision, recall),
        window_event_recall=_safe_rate(window_matches, covered),
    )


def sweep_daily_event_candidates(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    lookbacks: list[int],
    trigger_modes: list[DailyTriggerMode],
    event_window_days: int = 3,
) -> list[DailySweepResult]:
    results = [
        evaluate_daily_sweep_candidate(
            observations,
            bars_by_ticker,
            candidate=DailySweepCandidate(lookback_sessions=lookback, trigger_mode=mode),
            event_window_days=event_window_days,
        )
        for lookback in lookbacks
        for mode in trigger_modes
    ]
    results.sort(
        key=lambda item: (
            item.exact_event_f1 or 0,
            item.exact_event_recall or 0,
            item.carried_state_accuracy or 0,
        ),
        reverse=True,
    )
    return results
