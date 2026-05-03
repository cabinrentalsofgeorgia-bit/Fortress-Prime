"""Promotion review helpers for Dochia signal candidates."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

LANE_ORDER = ("bullish_alignment", "risk_alignment", "reentry", "mixed_timeframes")


@dataclass(frozen=True, slots=True)
class LaneReview:
    lane: str
    baseline_count: int
    candidate_count: int
    overlap_count: int
    entered_count: int
    exited_count: int
    entered: list[str]
    exited: list[str]

    @property
    def churn_rate(self) -> float:
        denominator = max(self.baseline_count + self.candidate_count - self.overlap_count, 1)
        return (self.entered_count + self.exited_count) / denominator


@dataclass(frozen=True, slots=True)
class WhipsawCluster:
    ticker: str
    baseline_transition_count: int
    candidate_transition_count: int
    transition_delta: int
    baseline_daily_transition_count: int
    candidate_daily_transition_count: int
    candidate_transition_types: dict[str, int]
    latest_candidate_transition_date: str | None


@dataclass(frozen=True, slots=True)
class ChartEventReview:
    ticker: str
    baseline_daily_event_count: int
    candidate_daily_event_count: int
    daily_event_delta: int
    candidate_only_count: int
    candidate_only_events: list[dict[str, Any]]


def _event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("bar_date") or ""), str(event.get("state") or ""))


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        out = asdict(value)
        if isinstance(value, LaneReview):
            out["churn_rate"] = value.churn_rate
        return _jsonable(out)
    return value


def as_jsonable(value: object) -> object:
    return _jsonable(value)


def _ticker_set(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")}


def build_lane_reviews(
    baseline_lanes: dict[str, list[dict[str, Any]]],
    candidate_lanes: dict[str, list[dict[str, Any]]],
    *,
    sample_size: int = 12,
) -> list[LaneReview]:
    reviews: list[LaneReview] = []
    for lane in LANE_ORDER:
        baseline = _ticker_set(baseline_lanes.get(lane, []))
        candidate = _ticker_set(candidate_lanes.get(lane, []))
        entered = sorted(candidate - baseline)
        exited = sorted(baseline - candidate)
        reviews.append(
            LaneReview(
                lane=lane,
                baseline_count=len(baseline),
                candidate_count=len(candidate),
                overlap_count=len(baseline & candidate),
                entered_count=len(entered),
                exited_count=len(exited),
                entered=entered[:sample_size],
                exited=exited[:sample_size],
            )
        )
    return reviews


def _is_daily_transition(row: dict[str, Any]) -> bool:
    notes = str(row.get("notes") or "").lower()
    return notes.startswith("daily triangle") or " daily triangle " in notes


def _transition_date(row: dict[str, Any]) -> str | None:
    value = row.get("to_bar_date")
    if value is None:
        return None
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return str(value)


def _transition_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        grouped.setdefault(ticker, []).append(row)
    return grouped


def build_whipsaw_clusters(
    baseline_transitions: list[dict[str, Any]],
    candidate_transitions: list[dict[str, Any]],
    *,
    min_candidate_transitions: int = 4,
    min_transition_delta: int = 2,
    top: int = 15,
) -> list[WhipsawCluster]:
    baseline_by_ticker = _transition_groups(baseline_transitions)
    candidate_by_ticker = _transition_groups(candidate_transitions)
    clusters: list[WhipsawCluster] = []
    for ticker in sorted(set(baseline_by_ticker) | set(candidate_by_ticker)):
        baseline_rows = baseline_by_ticker.get(ticker, [])
        candidate_rows = candidate_by_ticker.get(ticker, [])
        baseline_count = len(baseline_rows)
        candidate_count = len(candidate_rows)
        delta = candidate_count - baseline_count
        if candidate_count < min_candidate_transitions and delta < min_transition_delta:
            continue
        candidate_type_counts = Counter(
            str(row.get("transition_type") or "unknown") for row in candidate_rows
        )
        candidate_dates = [date for row in candidate_rows if (date := _transition_date(row))]
        clusters.append(
            WhipsawCluster(
                ticker=ticker,
                baseline_transition_count=baseline_count,
                candidate_transition_count=candidate_count,
                transition_delta=delta,
                baseline_daily_transition_count=sum(_is_daily_transition(row) for row in baseline_rows),
                candidate_daily_transition_count=sum(_is_daily_transition(row) for row in candidate_rows),
                candidate_transition_types=dict(sorted(candidate_type_counts.items())),
                latest_candidate_transition_date=max(candidate_dates) if candidate_dates else None,
            )
        )
    clusters.sort(
        key=lambda item: (
            item.candidate_transition_count,
            item.transition_delta,
            item.candidate_daily_transition_count,
            item.ticker,
        ),
        reverse=True,
    )
    return clusters[:top]


def _daily_event_keys(chart: dict[str, Any]) -> set[tuple[str, str]]:
    keys = set()
    for event in chart.get("events", []):
        if event.get("timeframe") != "daily":
            continue
        keys.add((str(event.get("bar_date")), str(event.get("state"))))
    return keys


def _candidate_only_events(
    candidate_chart: dict[str, Any],
    baseline_keys: set[tuple[str, str]],
    *,
    sample_size: int,
) -> list[dict[str, Any]]:
    events = []
    for event in candidate_chart.get("events", []):
        if event.get("timeframe") != "daily":
            continue
        key = (str(event.get("bar_date")), str(event.get("state")))
        if key in baseline_keys:
            continue
        events.append(
            {
                "bar_date": event.get("bar_date"),
                "state": event.get("state"),
                "trigger_price": event.get("trigger_price"),
                "reason": event.get("reason"),
            }
        )
    events.sort(key=_event_sort_key, reverse=True)
    return events[:sample_size]


def build_chart_event_reviews(
    baseline_charts: dict[str, dict[str, Any]],
    candidate_charts: dict[str, dict[str, Any]],
    *,
    sample_size: int = 5,
) -> list[ChartEventReview]:
    reviews: list[ChartEventReview] = []
    for ticker in sorted(set(baseline_charts) & set(candidate_charts)):
        baseline_keys = _daily_event_keys(baseline_charts[ticker])
        candidate_keys = _daily_event_keys(candidate_charts[ticker])
        candidate_only = _candidate_only_events(
            candidate_charts[ticker],
            baseline_keys,
            sample_size=sample_size,
        )
        delta = len(candidate_keys) - len(baseline_keys)
        if delta == 0 and not candidate_only:
            continue
        reviews.append(
            ChartEventReview(
                ticker=ticker,
                baseline_daily_event_count=len(baseline_keys),
                candidate_daily_event_count=len(candidate_keys),
                daily_event_delta=delta,
                candidate_only_count=len(candidate_keys - baseline_keys),
                candidate_only_events=candidate_only,
            )
        )
    reviews.sort(
        key=lambda item: (
            abs(item.daily_event_delta),
            item.candidate_only_count,
            item.ticker,
        ),
        reverse=True,
    )
    return reviews


def focus_tickers_for_chart_review(
    *,
    lane_reviews: list[LaneReview],
    whipsaw_clusters: list[WhipsawCluster],
    candidate_lanes: dict[str, list[dict[str, Any]]],
    limit: int,
) -> list[str]:
    ordered: list[str] = []

    def add(ticker: str) -> None:
        normalized = ticker.upper()
        if normalized and normalized not in ordered:
            ordered.append(normalized)

    for review in lane_reviews:
        for ticker in review.entered + review.exited:
            add(ticker)
    for cluster in whipsaw_clusters:
        add(cluster.ticker)
    for lane in LANE_ORDER:
        for row in candidate_lanes.get(lane, []):
            add(str(row.get("ticker") or ""))
    return ordered[:limit]
