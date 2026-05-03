"""Read-only comparison of production and candidate signal-lane outputs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.db_preview import (  # noqa: E402
    SignalScorePreview,
    SignalTransitionPreview,
    eod_row_to_bar,
    preview_from_snapshot,
    transition_previews_from_snapshot,
)
from app.signals.trade_triangles import latest_triangle_snapshot  # noqa: E402
from scripts.sync_signal_scores import (  # noqa: E402
    _database_url,
    _fetch_bars,
    _fetch_candidate_tickers,
    _fetch_parameter_set,
    _fetch_reference_date,
    _is_fresh_enough,
    _resolve_daily_trigger_mode,
)

LANES = ("bullish_alignment", "risk_alignment", "reentry", "mixed_timeframes")
REENTRY_TRANSITIONS = {"exit_to_reentry", "breakout_bullish"}


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    preview: SignalScorePreview
    latest_transition_type: str | None
    latest_transition_bar_date: str | None


@dataclass(frozen=True, slots=True)
class LaneDelta:
    lane: str
    baseline_count: int
    candidate_count: int
    entered_count: int
    exited_count: int
    entered: list[str]
    exited: list[str]


@dataclass(frozen=True, slots=True)
class ScoreDelta:
    ticker: str
    baseline_score: int
    candidate_score: int
    delta: int
    baseline_states: dict[str, int]
    candidate_states: dict[str, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare production signal lanes against a non-production candidate."
    )
    parser.add_argument("--baseline-parameter-set", default=None)
    parser.add_argument("--baseline-daily-trigger-mode", choices=["close", "range"], default=None)
    parser.add_argument("--candidate-parameter-set", default="dochia_v0_2_range_daily")
    parser.add_argument("--candidate-daily-trigger-mode", choices=["close", "range"], default=None)
    parser.add_argument("--ticker", action="append", dest="tickers")
    parser.add_argument("--limit-tickers", type=int, default=500)
    parser.add_argument("--min-bars", type=int, default=64)
    parser.add_argument("--max-stale-days", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _state_dict(preview: SignalScorePreview) -> dict[str, int]:
    return {
        "monthly": preview.monthly_state,
        "weekly": preview.weekly_state,
        "daily": preview.daily_state,
        "momentum": preview.momentum_state,
    }


def _latest_transition(previews: list[SignalTransitionPreview]) -> SignalTransitionPreview | None:
    if not previews:
        return None
    return max(previews, key=lambda item: (item.to_bar_date, item.transition_type))


def _snapshot_for_parameter(
    *,
    bars: list[dict[str, Any]],
    parameter_set: dict[str, Any],
    explicit_daily_trigger_mode: str | None,
    since: dt.date,
) -> CandidateSnapshot:
    eod_bars = [eod_row_to_bar(row) for row in bars]
    daily_trigger_mode = _resolve_daily_trigger_mode(
        str(parameter_set["name"]),
        explicit_daily_trigger_mode,
    )
    triangle_snapshot = latest_triangle_snapshot(
        eod_bars,
        daily_trigger_mode=daily_trigger_mode,
        daily_lookback_sessions=int(parameter_set["daily_lookback_days"]),
        weekly_lookback_sessions=int(parameter_set["weekly_lookback_days"]),
        monthly_lookback_sessions=int(parameter_set["monthly_lookback_days"]),
    )
    preview = preview_from_snapshot(
        triangle_snapshot,
        parameter_set_name=str(parameter_set["name"]),
        monthly_weight=int(parameter_set["weight_monthly"]),
        weekly_weight=int(parameter_set["weight_weekly"]),
        daily_weight=int(parameter_set["weight_daily"]),
        momentum_weight=int(parameter_set["weight_momentum"]),
    )
    transitions = transition_previews_from_snapshot(
        triangle_snapshot,
        parameter_set_name=str(parameter_set["name"]),
        monthly_weight=int(parameter_set["weight_monthly"]),
        weekly_weight=int(parameter_set["weight_weekly"]),
        daily_weight=int(parameter_set["weight_daily"]),
        momentum_weight=int(parameter_set["weight_momentum"]),
        since=since,
    )
    latest_transition = _latest_transition(transitions)
    return CandidateSnapshot(
        preview=preview,
        latest_transition_type=latest_transition.transition_type if latest_transition else None,
        latest_transition_bar_date=latest_transition.to_bar_date if latest_transition else None,
    )


def _lane_membership(snapshot: CandidateSnapshot) -> set[str]:
    preview = snapshot.preview
    lanes: set[str] = set()
    if preview.composite_score >= 50:
        lanes.add("bullish_alignment")
    if preview.composite_score <= -50:
        lanes.add("risk_alignment")
    if (
        snapshot.latest_transition_type in REENTRY_TRANSITIONS
        and preview.composite_score >= 0
    ):
        lanes.add("reentry")
    if (
        preview.monthly_state != preview.weekly_state
        or preview.weekly_state != preview.daily_state
    ):
        lanes.add("mixed_timeframes")
    return lanes


def _lane_sets(snapshots: dict[str, CandidateSnapshot]) -> dict[str, set[str]]:
    lanes = {lane: set() for lane in LANES}
    for ticker, snapshot in snapshots.items():
        for lane in _lane_membership(snapshot):
            lanes[lane].add(ticker)
    return lanes


def _lane_deltas(
    baseline: dict[str, set[str]],
    candidate: dict[str, set[str]],
    *,
    top: int,
) -> list[LaneDelta]:
    deltas = []
    for lane in LANES:
        entered = sorted(candidate[lane] - baseline[lane])
        exited = sorted(baseline[lane] - candidate[lane])
        deltas.append(
            LaneDelta(
                lane=lane,
                baseline_count=len(baseline[lane]),
                candidate_count=len(candidate[lane]),
                entered_count=len(entered),
                exited_count=len(exited),
                entered=entered[:top],
                exited=exited[:top],
            )
        )
    return deltas


def _score_deltas(
    baseline: dict[str, CandidateSnapshot],
    candidate: dict[str, CandidateSnapshot],
) -> list[ScoreDelta]:
    deltas = []
    for ticker in sorted(set(baseline) & set(candidate)):
        baseline_preview = baseline[ticker].preview
        candidate_preview = candidate[ticker].preview
        delta = candidate_preview.composite_score - baseline_preview.composite_score
        if delta == 0:
            continue
        deltas.append(
            ScoreDelta(
                ticker=ticker,
                baseline_score=baseline_preview.composite_score,
                candidate_score=candidate_preview.composite_score,
                delta=delta,
                baseline_states=_state_dict(baseline_preview),
                candidate_states=_state_dict(candidate_preview),
            )
        )
    deltas.sort(key=lambda item: (abs(item.delta), item.ticker), reverse=True)
    return deltas


def _build_snapshots(
    *,
    conn: psycopg.Connection,
    tickers: list[str],
    parameter_set: dict[str, Any],
    explicit_daily_trigger_mode: str | None,
    args: argparse.Namespace,
    reference_date: dt.date,
    since: dt.date,
) -> dict[str, CandidateSnapshot]:
    snapshots: dict[str, CandidateSnapshot] = {}
    for ticker in tickers:
        rows = _fetch_bars(conn, ticker.upper(), args.as_of)
        if len(rows) < args.min_bars:
            continue
        snapshot = _snapshot_for_parameter(
            bars=rows,
            parameter_set=parameter_set,
            explicit_daily_trigger_mode=explicit_daily_trigger_mode,
            since=since,
        )
        if not args.include_stale and not _is_fresh_enough(
            dt.date.fromisoformat(snapshot.preview.bar_date),
            reference_date=reference_date,
            max_stale_days=args.max_stale_days,
        ):
            continue
        snapshots[ticker.upper()] = snapshot
    return snapshots


def _as_jsonable(value: object) -> object:
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    if hasattr(value, "as_json_dict"):
        return value.as_json_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _as_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _as_jsonable(item) for key, item in value.items()}
    return value


def _print_report(
    *,
    baseline_parameter_set: dict[str, Any],
    candidate_parameter_set: dict[str, Any],
    reference_date: dt.date,
    since: dt.date,
    baseline_snapshots: dict[str, CandidateSnapshot],
    candidate_snapshots: dict[str, CandidateSnapshot],
    lane_deltas: list[LaneDelta],
    score_deltas: list[ScoreDelta],
    total_score_delta_count: int,
) -> None:
    print("Signal candidate lane comparison")
    print(
        f"baseline={baseline_parameter_set['name']} "
        f"candidate={candidate_parameter_set['name']}"
    )
    print(
        f"reference_date={reference_date.isoformat()} since={since.isoformat()} "
        f"tickers={len(candidate_snapshots)}"
    )
    print()
    print("lane              | baseline | candidate | entered | exited | sample entered")
    print("------------------|----------|-----------|---------|--------|----------------")
    for row in lane_deltas:
        print(
            f"{row.lane:<17} | "
            f"{row.baseline_count:>8} | "
            f"{row.candidate_count:>9} | "
            f"{row.entered_count:>7} | "
            f"{row.exited_count:>6} | "
            f"{', '.join(row.entered) or '-'}"
        )
    print()
    changed_daily = sum(
        1
        for ticker, baseline in baseline_snapshots.items()
        if ticker in candidate_snapshots
        and baseline.preview.daily_state != candidate_snapshots[ticker].preview.daily_state
    )
    print(
        f"daily_state_changes={changed_daily} "
        f"score_changes={total_score_delta_count} "
        f"score_changes_shown={len(score_deltas)}"
    )
    print()
    print("ticker | score delta | baseline | candidate | states")
    print("-------|-------------|----------|-----------|------------------------------")
    for row in score_deltas:
        print(
            f"{row.ticker:<6} | "
            f"{row.delta:+11d} | "
            f"{row.baseline_score:+8d} | "
            f"{row.candidate_score:+9d} | "
            f"{row.baseline_states} -> {row.candidate_states}"
        )


def main() -> None:
    args = parse_args()
    if args.limit_tickers < 1:
        raise SystemExit("limit-tickers must be at least 1")
    if args.min_bars < 1:
        raise SystemExit("min-bars must be at least 1")

    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        baseline_parameter_set = _fetch_parameter_set(conn, args.baseline_parameter_set)
        candidate_parameter_set = _fetch_parameter_set(conn, args.candidate_parameter_set)
        reference_date = _fetch_reference_date(conn, args.as_of)
        since = reference_date - dt.timedelta(days=args.lookback_days)
        tickers = args.tickers or _fetch_candidate_tickers(
            conn,
            limit=args.limit_tickers,
            min_bars=args.min_bars,
            as_of=args.as_of,
            include_stale=args.include_stale,
            reference_date=reference_date,
            max_stale_days=args.max_stale_days,
        )
        baseline_snapshots = _build_snapshots(
            conn=conn,
            tickers=tickers,
            parameter_set=baseline_parameter_set,
            explicit_daily_trigger_mode=args.baseline_daily_trigger_mode,
            args=args,
            reference_date=reference_date,
            since=since,
        )
        candidate_snapshots = _build_snapshots(
            conn=conn,
            tickers=tickers,
            parameter_set=candidate_parameter_set,
            explicit_daily_trigger_mode=args.candidate_daily_trigger_mode,
            args=args,
            reference_date=reference_date,
            since=since,
        )

    lane_deltas = _lane_deltas(
        _lane_sets(baseline_snapshots),
        _lane_sets(candidate_snapshots),
        top=args.top,
    )
    all_score_deltas = _score_deltas(
        baseline_snapshots,
        candidate_snapshots,
    )
    score_deltas = all_score_deltas[: args.top]
    payload = {
        "baseline_parameter_set": baseline_parameter_set["name"],
        "candidate_parameter_set": candidate_parameter_set["name"],
        "reference_date": reference_date.isoformat(),
        "since": since.isoformat(),
        "ticker_count": len(candidate_snapshots),
        "lane_deltas": lane_deltas,
        "score_delta_count": len(all_score_deltas),
        "score_deltas": score_deltas,
    }
    if args.json:
        print(json.dumps(_as_jsonable(payload), indent=2, sort_keys=True))
    else:
        _print_report(
            baseline_parameter_set=baseline_parameter_set,
            candidate_parameter_set=candidate_parameter_set,
            reference_date=reference_date,
            since=since,
            baseline_snapshots=baseline_snapshots,
            candidate_snapshots=candidate_snapshots,
            lane_deltas=lane_deltas,
            score_deltas=score_deltas,
            total_score_delta_count=len(all_score_deltas),
        )


if __name__ == "__main__":
    main()
