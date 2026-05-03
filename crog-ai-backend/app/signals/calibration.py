"""Calibration helpers for comparing Dochia signals to MarketClub observations."""

from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from app.signals.trade_triangles import (
    EodBar,
    TriangleTimeframe,
    detect_triangle_events,
)

STATE_BY_LABEL = {"red": -1, "neutral": 0, "green": 1}
STATE_LABELS = {-1: "red", 0: "neutral", 1: "green"}
CONFUSION_LABELS = ("green", "red", "neutral", "missing")
EVENT_CONFUSION_LABELS = ("green", "red", "none", "missing")


@dataclass(frozen=True, slots=True)
class CalibrationWeights:
    monthly: int
    weekly: int
    daily: int
    momentum: int


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    ticker: str
    trading_day: dt.date
    triangle_color: str
    score: int


@dataclass(frozen=True, slots=True)
class GeneratedCalibrationState:
    ticker: str
    bar_date: dt.date
    monthly_state: int
    weekly_state: int
    daily_state: int
    momentum_state: int
    composite_score: int


@dataclass(frozen=True, slots=True)
class GeneratedCalibrationHistory:
    ticker: str
    dates: tuple[dt.date, ...]
    states_by_date: dict[dt.date, GeneratedCalibrationState]
    daily_events_by_date: dict[dt.date, int]
    daily_event_dates_by_state: dict[int, tuple[dt.date, ...]]

    def as_of(self, trading_day: dt.date) -> GeneratedCalibrationState | None:
        index = bisect_right(self.dates, trading_day) - 1
        if index < 0:
            return None
        return self.states_by_date[self.dates[index]]

    def daily_event_on(self, trading_day: dt.date) -> int | None:
        return self.daily_events_by_date.get(trading_day)

    def has_daily_event_within(
        self,
        *,
        trading_day: dt.date,
        state: int,
        window_days: int,
    ) -> bool:
        for event_date in self.daily_event_dates_by_state.get(state, ()):
            if abs((event_date - trading_day).days) <= window_days:
                return True
        return False


@dataclass(frozen=True, slots=True)
class TickerCalibrationStats:
    ticker: str
    observations: int
    covered_observations: int
    exact_bar_observations: int
    matches: int
    accuracy: float | None
    score_mae: float | None


@dataclass(frozen=True, slots=True)
class DailyCalibrationResult:
    parameter_set_name: str
    generated_at: dt.datetime
    since: dt.date | None
    until: dt.date | None
    total_observations: int
    covered_observations: int
    exact_bar_observations: int
    missing_observations: int
    neutral_generated_observations: int
    matches: int
    exact_event_matches: int
    exact_event_accuracy: float | None
    window_event_matches: int
    window_event_accuracy: float | None
    event_window_days: int
    no_generated_event_observations: int
    opposite_generated_event_observations: int
    accuracy: float | None
    coverage_rate: float | None
    exact_coverage_rate: float | None
    green_precision: float | None
    green_recall: float | None
    red_precision: float | None
    red_recall: float | None
    score_mae: float | None
    score_rmse: float | None
    confusion: dict[str, dict[str, int]]
    event_confusion: dict[str, dict[str, int]]
    top_tickers: list[TickerCalibrationStats]

    def as_json_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["generated_at"] = self.generated_at.isoformat()
        out["since"] = self.since.isoformat() if self.since else None
        out["until"] = self.until.isoformat() if self.until else None
        return out


def normalize_triangle_color(value: str) -> str:
    color = value.strip().lower()
    if color not in {"green", "red"}:
        raise ValueError(f"unsupported triangle color: {value}")
    return color


def generated_state_history(
    bars: list[EodBar],
    *,
    weights: CalibrationWeights,
    momentum_state: int = 0,
) -> GeneratedCalibrationHistory | None:
    ordered = sorted(bars, key=lambda bar: (bar.ticker, bar.bar_date))
    if not ordered:
        return None
    ticker = ordered[0].ticker
    if any(bar.ticker != ticker for bar in ordered):
        raise ValueError("bars must contain exactly one ticker")

    events_by_date: dict[dt.date, list[tuple[TriangleTimeframe, int]]] = defaultdict(list)
    daily_events_by_date: dict[dt.date, int] = {}
    daily_event_dates_by_state: dict[int, list[dt.date]] = defaultdict(list)
    for timeframe in TriangleTimeframe:
        for event in detect_triangle_events(ordered, timeframe):
            events_by_date[event.bar_date].append((timeframe, event.state.numeric))
            if timeframe is TriangleTimeframe.DAILY:
                daily_events_by_date[event.bar_date] = event.state.numeric
                daily_event_dates_by_state[event.state.numeric].append(event.bar_date)

    monthly_state = 0
    weekly_state = 0
    daily_state = 0
    states_by_date: dict[dt.date, GeneratedCalibrationState] = {}
    dates: list[dt.date] = []

    for bar in ordered:
        for timeframe, state in events_by_date.get(bar.bar_date, []):
            if timeframe is TriangleTimeframe.MONTHLY:
                monthly_state = state
            elif timeframe is TriangleTimeframe.WEEKLY:
                weekly_state = state
            elif timeframe is TriangleTimeframe.DAILY:
                daily_state = state

        composite_score = (
            monthly_state * weights.monthly
            + weekly_state * weights.weekly
            + daily_state * weights.daily
            + momentum_state * weights.momentum
        )
        states_by_date[bar.bar_date] = GeneratedCalibrationState(
            ticker=ticker,
            bar_date=bar.bar_date,
            monthly_state=monthly_state,
            weekly_state=weekly_state,
            daily_state=daily_state,
            momentum_state=momentum_state,
            composite_score=composite_score,
        )
        dates.append(bar.bar_date)

    return GeneratedCalibrationHistory(
        ticker=ticker,
        dates=tuple(dates),
        states_by_date=states_by_date,
        daily_events_by_date=daily_events_by_date,
        daily_event_dates_by_state={
            state: tuple(sorted(event_dates))
            for state, event_dates in daily_event_dates_by_state.items()
        },
    )


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _score_mae(deltas: list[int]) -> float | None:
    if not deltas:
        return None
    return sum(abs(delta) for delta in deltas) / len(deltas)


def _score_rmse(deltas: list[int]) -> float | None:
    if not deltas:
        return None
    return math.sqrt(sum(delta * delta for delta in deltas) / len(deltas))


def evaluate_daily_calibration(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    parameter_set_name: str,
    weights: CalibrationWeights,
    since: dt.date | None = None,
    until: dt.date | None = None,
    top_ticker_count: int = 20,
    event_window_days: int = 3,
) -> DailyCalibrationResult:
    histories = {
        ticker: history
        for ticker, bars in bars_by_ticker.items()
        if (history := generated_state_history(bars, weights=weights)) is not None
    }

    confusion = {actual: dict.fromkeys(CONFUSION_LABELS, 0) for actual in ("green", "red")}
    event_confusion = {
        actual: dict.fromkeys(EVENT_CONFUSION_LABELS, 0) for actual in ("green", "red")
    }
    ticker_counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"observations": 0, "covered": 0, "exact": 0, "matches": 0, "score_deltas": []}
    )

    covered = 0
    exact = 0
    missing = 0
    neutral = 0
    matches = 0
    exact_event_matches = 0
    window_event_matches = 0
    no_event = 0
    opposite_event = 0
    score_deltas: list[int] = []

    for observation in observations:
        actual = normalize_triangle_color(observation.triangle_color)
        stats = ticker_counts[observation.ticker]
        stats["observations"] += 1

        history = histories.get(observation.ticker)
        generated_state = history.as_of(observation.trading_day) if history else None
        if generated_state is None:
            generated = "missing"
            event_generated = "missing"
            missing += 1
        else:
            covered += 1
            stats["covered"] += 1
            if generated_state.bar_date == observation.trading_day:
                exact += 1
                stats["exact"] += 1
            generated = STATE_LABELS[generated_state.daily_state]
            if generated == "neutral":
                neutral += 1
            if generated == actual:
                matches += 1
                stats["matches"] += 1
            delta = observation.score - generated_state.composite_score
            score_deltas.append(delta)
            stats["score_deltas"].append(delta)

            actual_state = STATE_BY_LABEL[actual]
            generated_event_state = history.daily_event_on(observation.trading_day)
            if generated_event_state is None:
                event_generated = "none"
                no_event += 1
            else:
                event_generated = STATE_LABELS[generated_event_state]
                if event_generated == actual:
                    exact_event_matches += 1
                else:
                    opposite_event += 1
            if history.has_daily_event_within(
                trading_day=observation.trading_day,
                state=actual_state,
                window_days=event_window_days,
            ):
                window_event_matches += 1

        confusion[actual][generated] += 1
        event_confusion[actual][event_generated] += 1

    top_tickers = [
        TickerCalibrationStats(
            ticker=ticker,
            observations=int(stats["observations"]),
            covered_observations=int(stats["covered"]),
            exact_bar_observations=int(stats["exact"]),
            matches=int(stats["matches"]),
            accuracy=_safe_rate(int(stats["matches"]), int(stats["covered"])),
            score_mae=_score_mae(stats["score_deltas"]),
        )
        for ticker, stats in ticker_counts.items()
    ]
    top_tickers.sort(key=lambda item: (-item.observations, item.ticker))

    green_true_positive = confusion["green"]["green"]
    red_true_positive = confusion["red"]["red"]
    generated_green = confusion["green"]["green"] + confusion["red"]["green"]
    generated_red = confusion["red"]["red"] + confusion["green"]["red"]
    covered_green_actual = sum(
        confusion["green"][label] for label in ("green", "red", "neutral")
    )
    covered_red_actual = sum(confusion["red"][label] for label in ("green", "red", "neutral"))

    total = len(observations)
    return DailyCalibrationResult(
        parameter_set_name=parameter_set_name,
        generated_at=dt.datetime.now(dt.UTC),
        since=since,
        until=until,
        total_observations=total,
        covered_observations=covered,
        exact_bar_observations=exact,
        missing_observations=missing,
        neutral_generated_observations=neutral,
        matches=matches,
        exact_event_matches=exact_event_matches,
        exact_event_accuracy=_safe_rate(exact_event_matches, covered),
        window_event_matches=window_event_matches,
        window_event_accuracy=_safe_rate(window_event_matches, covered),
        event_window_days=event_window_days,
        no_generated_event_observations=no_event,
        opposite_generated_event_observations=opposite_event,
        accuracy=_safe_rate(matches, covered),
        coverage_rate=_safe_rate(covered, total),
        exact_coverage_rate=_safe_rate(exact, total),
        green_precision=_safe_rate(green_true_positive, generated_green),
        green_recall=_safe_rate(green_true_positive, covered_green_actual),
        red_precision=_safe_rate(red_true_positive, generated_red),
        red_recall=_safe_rate(red_true_positive, covered_red_actual),
        score_mae=_score_mae(score_deltas),
        score_rmse=_score_rmse(score_deltas),
        confusion=confusion,
        event_confusion=event_confusion,
        top_tickers=top_tickers[:top_ticker_count],
    )
