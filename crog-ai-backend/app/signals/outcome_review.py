"""Forward-return and whipsaw review helpers for Dochia signal candidates."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import asdict, dataclass
from statistics import median

from app.signals.calibration import CalibrationObservation, normalize_triangle_color
from app.signals.calibration_sweep import DailyEventHistory
from app.signals.trade_triangles import EodBar, TriangleState


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


@dataclass(frozen=True, slots=True)
class AlertMatchSummary:
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


@dataclass(frozen=True, slots=True)
class TickerClusterCandidate:
    cluster_size: int
    mode: str
    cooldown_sessions: int = 0

    @property
    def name(self) -> str:
        if self.mode == "exclude":
            return f"top_{self.cluster_size}_exclude"
        return f"top_{self.cluster_size}_cooldown_{self.cooldown_sessions}"

    def as_json_dict(self) -> dict[str, object]:
        return asdict(self) | {"name": self.name}


@dataclass(frozen=True, slots=True)
class TickerClusterReview:
    candidate: TickerClusterCandidate
    cluster_tickers: list[str]
    alert_match: AlertMatchSummary
    generated_event_reduction: float | None
    outcome_5_session: ReturnOutcomeSummary
    top_whipsaw_count: int
    top_whipsaw_tickers: list[str]

    def as_json_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_json_dict(),
            "cluster_tickers": self.cluster_tickers,
            "alert_match": self.alert_match.as_json_dict(),
            "generated_event_reduction": self.generated_event_reduction,
            "outcome_5_session": self.outcome_5_session.as_json_dict(),
            "top_whipsaw_count": self.top_whipsaw_count,
            "top_whipsaw_tickers": self.top_whipsaw_tickers,
        }


@dataclass(frozen=True, slots=True)
class RollingWhipsawCandidate:
    risk_lookback_sessions: int
    min_whipsaws: int
    cooldown_sessions: int
    whipsaw_window_sessions: int = 5

    @property
    def name(self) -> str:
        return (
            f"rolling_{self.risk_lookback_sessions}_"
            f"{self.min_whipsaws}_cooldown_{self.cooldown_sessions}"
        )

    def as_json_dict(self) -> dict[str, object]:
        return asdict(self) | {"name": self.name}


@dataclass(frozen=True, slots=True)
class RollingWhipsawReview:
    candidate: RollingWhipsawCandidate
    alert_match: AlertMatchSummary
    generated_event_reduction: float | None
    outcome_5_session: ReturnOutcomeSummary
    top_whipsaw_count: int
    top_whipsaw_tickers: list[str]

    def as_json_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_json_dict(),
            "alert_match": self.alert_match.as_json_dict(),
            "generated_event_reduction": self.generated_event_reduction,
            "outcome_5_session": self.outcome_5_session.as_json_dict(),
            "top_whipsaw_count": self.top_whipsaw_count,
            "top_whipsaw_tickers": self.top_whipsaw_tickers,
        }


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


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


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


def _rebuild_history_from_events(
    history: DailyEventHistory,
    *,
    kept_events: dict[dt.date, int],
) -> DailyEventHistory:
    current_state = TriangleState.NEUTRAL.numeric
    state_by_date: dict[dt.date, int] = {}
    event_dates_by_state: dict[int, list[dt.date]] = defaultdict(list)

    for trading_day in history.dates:
        event_state = kept_events.get(trading_day)
        if event_state is not None:
            current_state = event_state
            event_dates_by_state[event_state].append(trading_day)
        state_by_date[trading_day] = current_state

    return DailyEventHistory(
        ticker=history.ticker,
        dates=history.dates,
        state_by_date=state_by_date,
        event_by_date=kept_events,
        event_dates_by_state={
            state: tuple(sorted(event_dates)) for state, event_dates in event_dates_by_state.items()
        },
    )


def apply_ticker_cluster_candidate(
    histories: dict[str, DailyEventHistory],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    cluster_tickers: set[str],
    candidate: TickerClusterCandidate,
) -> dict[str, DailyEventHistory]:
    if candidate.mode not in {"cooldown", "exclude"}:
        raise ValueError("candidate mode must be cooldown or exclude")
    if candidate.cluster_size < 1:
        raise ValueError("cluster_size must be at least 1")
    if candidate.cooldown_sessions < 0:
        raise ValueError("cooldown_sessions must be non-negative")

    adjusted: dict[str, DailyEventHistory] = {}
    for ticker, history in histories.items():
        if ticker not in cluster_tickers:
            adjusted[ticker] = history
            continue

        if candidate.mode == "exclude":
            adjusted[ticker] = _rebuild_history_from_events(history, kept_events={})
            continue

        bars = _ordered_bars(bars_by_ticker.get(ticker, []))
        index_by_date = {bar.bar_date: index for index, bar in enumerate(bars)}
        kept_events: dict[dt.date, int] = {}
        last_kept_index: int | None = None
        for event_date, event_state in sorted(history.event_by_date.items()):
            event_index = index_by_date.get(event_date)
            if event_index is None:
                continue
            within_cooldown = (
                last_kept_index is not None
                and event_index - last_kept_index <= candidate.cooldown_sessions
            )
            if within_cooldown:
                continue
            kept_events[event_date] = event_state
            last_kept_index = event_index
        adjusted[ticker] = _rebuild_history_from_events(history, kept_events=kept_events)
    return adjusted


def apply_rolling_whipsaw_candidate(
    histories: dict[str, DailyEventHistory],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    candidate: RollingWhipsawCandidate,
) -> dict[str, DailyEventHistory]:
    if candidate.risk_lookback_sessions < 1:
        raise ValueError("risk_lookback_sessions must be at least 1")
    if candidate.min_whipsaws < 1:
        raise ValueError("min_whipsaws must be at least 1")
    if candidate.cooldown_sessions < 1:
        raise ValueError("cooldown_sessions must be at least 1")
    if candidate.whipsaw_window_sessions < 1:
        raise ValueError("whipsaw_window_sessions must be at least 1")

    adjusted: dict[str, DailyEventHistory] = {}
    for ticker, history in histories.items():
        bars = _ordered_bars(bars_by_ticker.get(ticker, []))
        index_by_date = {bar.bar_date: index for index, bar in enumerate(bars)}
        raw_events = [
            SignalEvent(
                ticker=ticker,
                event_date=event_date,
                index=index_by_date[event_date],
                state=event_state,
            )
            for event_date, event_state in sorted(history.event_by_date.items())
            if event_date in index_by_date
        ]

        kept_events: dict[dt.date, int] = {}
        whipsaw_indices: list[int] = []
        cooldown_until_index: int | None = None
        previous_raw_event: SignalEvent | None = None
        for event in raw_events:
            recent_whipsaws = [
                whipsaw_index
                for whipsaw_index in whipsaw_indices
                if event.index - whipsaw_index <= candidate.risk_lookback_sessions
            ]
            whipsaw_indices = recent_whipsaws
            in_cooldown = cooldown_until_index is not None and event.index <= cooldown_until_index
            risk_active = len(recent_whipsaws) >= candidate.min_whipsaws or in_cooldown
            if risk_active:
                cooldown_until_index = max(
                    cooldown_until_index or event.index,
                    event.index + candidate.cooldown_sessions,
                )
            else:
                kept_events[event.event_date] = event.state

            if (
                previous_raw_event is not None
                and event.state != previous_raw_event.state
                and event.index - previous_raw_event.index <= candidate.whipsaw_window_sessions
            ):
                whipsaw_indices.append(event.index)
            previous_raw_event = event

        adjusted[ticker] = _rebuild_history_from_events(history, kept_events=kept_events)
    return adjusted


def evaluate_event_histories(
    observations: list[CalibrationObservation],
    histories: dict[str, DailyEventHistory],
    *,
    event_window_days: int = 3,
) -> AlertMatchSummary:
    if observations:
        since = min(observation.trading_day for observation in observations)
        until = max(observation.trading_day for observation in observations)
    else:
        since = until = None

    generated_events = 0
    for history in histories.values():
        for event_date in history.event_by_date:
            if since is not None and event_date < since:
                continue
            if until is not None and event_date > until:
                continue
            generated_events += 1

    covered = 0
    state_matches = 0
    exact_matches = 0
    window_matches = 0
    opposite_events = 0
    no_events = 0
    matched_generated_events: set[tuple[str, dt.date]] = set()

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
    return AlertMatchSummary(
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


def _first_outcome(
    events: list[SignalEvent],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    horizon_sessions: int,
) -> ReturnOutcomeSummary:
    return summarize_forward_returns(
        events,
        bars_by_ticker,
        horizons=[horizon_sessions],
    )[0]


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


def review_ticker_cluster_candidate(
    observations: list[CalibrationObservation],
    raw_histories: dict[str, DailyEventHistory],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    cluster_tickers: list[str],
    candidate: TickerClusterCandidate,
    raw_generated_events: int,
    event_window_days: int,
    whipsaw_window_sessions: int,
    outcome_horizon_sessions: int,
    top_whipsaws: int,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> TickerClusterReview:
    selected_tickers = set(cluster_tickers[: candidate.cluster_size])
    adjusted_histories = apply_ticker_cluster_candidate(
        raw_histories,
        bars_by_ticker,
        cluster_tickers=selected_tickers,
        candidate=candidate,
    )
    alert_match = evaluate_event_histories(
        observations,
        adjusted_histories,
        event_window_days=event_window_days,
    )
    events = events_from_histories(adjusted_histories, bars_by_ticker, since=since, until=until)
    whipsaws = build_ticker_whipsaw_outcomes(
        events,
        bars_by_ticker,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
        top=top_whipsaws,
    )
    return TickerClusterReview(
        candidate=candidate,
        cluster_tickers=cluster_tickers[: candidate.cluster_size],
        alert_match=alert_match,
        generated_event_reduction=_safe_rate(
            raw_generated_events - alert_match.generated_events,
            raw_generated_events,
        ),
        outcome_5_session=_first_outcome(
            events,
            bars_by_ticker,
            horizon_sessions=outcome_horizon_sessions,
        ),
        top_whipsaw_count=sum(row.whipsaw_count for row in whipsaws),
        top_whipsaw_tickers=[row.ticker for row in whipsaws],
    )


def review_rolling_whipsaw_candidate(
    observations: list[CalibrationObservation],
    raw_histories: dict[str, DailyEventHistory],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    candidate: RollingWhipsawCandidate,
    raw_generated_events: int,
    event_window_days: int,
    outcome_horizon_sessions: int,
    top_whipsaws: int,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> RollingWhipsawReview:
    adjusted_histories = apply_rolling_whipsaw_candidate(
        raw_histories,
        bars_by_ticker,
        candidate=candidate,
    )
    alert_match = evaluate_event_histories(
        observations,
        adjusted_histories,
        event_window_days=event_window_days,
    )
    events = events_from_histories(adjusted_histories, bars_by_ticker, since=since, until=until)
    whipsaws = build_ticker_whipsaw_outcomes(
        events,
        bars_by_ticker,
        whipsaw_window_sessions=candidate.whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
        top=top_whipsaws,
    )
    return RollingWhipsawReview(
        candidate=candidate,
        alert_match=alert_match,
        generated_event_reduction=_safe_rate(
            raw_generated_events - alert_match.generated_events,
            raw_generated_events,
        ),
        outcome_5_session=_first_outcome(
            events,
            bars_by_ticker,
            horizon_sessions=outcome_horizon_sessions,
        ),
        top_whipsaw_count=sum(row.whipsaw_count for row in whipsaws),
        top_whipsaw_tickers=[row.ticker for row in whipsaws],
    )
