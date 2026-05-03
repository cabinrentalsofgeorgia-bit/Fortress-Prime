"""Guardrail sweeps for noisy MarketClub range-trigger candidates."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal

from app.signals.calibration import CalibrationObservation, normalize_triangle_color
from app.signals.calibration_sweep import DailyEventHistory
from app.signals.trade_triangles import EodBar, TriangleState


@dataclass(frozen=True, slots=True)
class GuardedRangeCandidate:
    lookback_sessions: int
    min_break_pct: Decimal = Decimal("0")
    debounce_sessions: int = 0
    require_directional_close: bool = False


@dataclass(frozen=True, slots=True)
class GuardrailSweepResult:
    lookback_sessions: int
    min_break_pct: Decimal
    debounce_sessions: int
    require_directional_close: bool
    total_observations: int
    covered_observations: int
    generated_events: int
    raw_range_generated_events: int | None
    generated_event_reduction: float | None
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
        payload = asdict(self)
        payload["min_break_pct"] = str(self.min_break_pct)
        return payload


def _channel(reference_bars: list[EodBar]) -> tuple[Decimal, Decimal]:
    return (
        max(bar.high for bar in reference_bars),
        min(bar.low for bar in reference_bars),
    )


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _validate_candidate(candidate: GuardedRangeCandidate) -> None:
    if candidate.lookback_sessions < 1:
        raise ValueError("lookback_sessions must be at least 1")
    if candidate.min_break_pct < 0:
        raise ValueError("min_break_pct must be non-negative")
    if candidate.min_break_pct >= 1:
        raise ValueError("min_break_pct must be less than 1")
    if candidate.debounce_sessions < 0:
        raise ValueError("debounce_sessions must be non-negative")


def _guarded_range_break_state(
    bar: EodBar,
    *,
    channel_high: Decimal,
    channel_low: Decimal,
    candidate: GuardedRangeCandidate,
) -> int:
    high_threshold = channel_high * (Decimal("1") + candidate.min_break_pct)
    low_threshold = channel_low * (Decimal("1") - candidate.min_break_pct)
    broke_high = bar.high > high_threshold
    broke_low = bar.low < low_threshold

    if candidate.require_directional_close:
        broke_high = broke_high and bar.close >= bar.open
        broke_low = broke_low and bar.close < bar.open

    if broke_high and broke_low:
        return TriangleState.GREEN.numeric if bar.close >= bar.open else TriangleState.RED.numeric
    if broke_high:
        return TriangleState.GREEN.numeric
    if broke_low:
        return TriangleState.RED.numeric
    return TriangleState.NEUTRAL.numeric


def generated_guarded_range_event_history(
    bars: list[EodBar],
    *,
    candidate: GuardedRangeCandidate,
) -> DailyEventHistory | None:
    """Generate range-trigger events after applying v0.3 research guardrails.

    `debounce_sessions` suppresses flips for that many full sessions after a
    generated event. For example, a value of 1 suppresses the next-session flip.
    """
    _validate_candidate(candidate)
    ordered = sorted(bars, key=lambda bar: (bar.ticker, bar.bar_date))
    if not ordered:
        return None
    ticker = ordered[0].ticker
    if any(bar.ticker != ticker for bar in ordered):
        raise ValueError("bars must contain exactly one ticker")

    current_state = TriangleState.NEUTRAL.numeric
    last_event_index: int | None = None
    state_by_date: dict[dt.date, int] = {}
    event_by_date: dict[dt.date, int] = {}
    event_dates_by_state: dict[int, list[dt.date]] = defaultdict(list)
    dates: list[dt.date] = []

    for index, bar in enumerate(ordered):
        if index >= candidate.lookback_sessions:
            channel_high, channel_low = _channel(
                ordered[index - candidate.lookback_sessions : index]
            )
            next_state = _guarded_range_break_state(
                bar,
                channel_high=channel_high,
                channel_low=channel_low,
                candidate=candidate,
            )
            if next_state != TriangleState.NEUTRAL.numeric and next_state != current_state:
                within_debounce = (
                    last_event_index is not None
                    and index - last_event_index <= candidate.debounce_sessions
                )
                if not within_debounce:
                    current_state = next_state
                    last_event_index = index
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


def evaluate_guarded_range_candidate(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    candidate: GuardedRangeCandidate,
    raw_range_generated_events: int | None = None,
    event_window_days: int = 3,
) -> GuardrailSweepResult:
    histories = {
        ticker: history
        for ticker, bars in bars_by_ticker.items()
        if (history := generated_guarded_range_event_history(bars, candidate=candidate))
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
    generated_event_reduction = (
        _safe_rate(raw_range_generated_events - generated_events, raw_range_generated_events)
        if raw_range_generated_events
        else None
    )
    return GuardrailSweepResult(
        lookback_sessions=candidate.lookback_sessions,
        min_break_pct=candidate.min_break_pct,
        debounce_sessions=candidate.debounce_sessions,
        require_directional_close=candidate.require_directional_close,
        total_observations=len(observations),
        covered_observations=covered,
        generated_events=generated_events,
        raw_range_generated_events=raw_range_generated_events,
        generated_event_reduction=generated_event_reduction,
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


def _sort_key(result: GuardrailSweepResult) -> tuple[float, float, float, float, int]:
    return (
        result.exact_event_f1 or 0,
        result.generated_event_reduction or 0,
        result.exact_event_precision or 0,
        result.window_event_recall or 0,
        -result.generated_events,
    )


def sweep_guarded_range_candidates(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    candidates: list[GuardedRangeCandidate],
    event_window_days: int = 3,
) -> list[GuardrailSweepResult]:
    raw_generated_by_lookback: dict[int, int] = {}
    for lookback in sorted({candidate.lookback_sessions for candidate in candidates}):
        raw_candidate = GuardedRangeCandidate(lookback_sessions=lookback)
        raw_result = evaluate_guarded_range_candidate(
            observations,
            bars_by_ticker,
            candidate=raw_candidate,
            event_window_days=event_window_days,
        )
        raw_generated_by_lookback[lookback] = raw_result.generated_events

    results = [
        evaluate_guarded_range_candidate(
            observations,
            bars_by_ticker,
            candidate=candidate,
            raw_range_generated_events=raw_generated_by_lookback.get(candidate.lookback_sessions),
            event_window_days=event_window_days,
        )
        for candidate in candidates
    ]
    results.sort(key=_sort_key, reverse=True)
    return results
