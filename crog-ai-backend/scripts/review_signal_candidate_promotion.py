#!/usr/bin/env python3
"""Build a read-only promotion review for a Dochia signal candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.chart_repository import fetch_symbol_chart  # noqa: E402
from app.signals.promotion_review import (  # noqa: E402
    as_jsonable,
    build_chart_event_reviews,
    build_lane_reviews,
    build_whipsaw_clusters,
    focus_tickers_for_chart_review,
)
from app.signals.repository import (  # noqa: E402
    fetch_recent_transitions,
    fetch_watchlist_candidates,
)
from scripts.sync_signal_scores import _database_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review whether a non-production signal candidate is ready for promotion."
    )
    parser.add_argument("--baseline-parameter-set", default=None)
    parser.add_argument("--candidate-parameter-set", default="dochia_v0_2_range_daily")
    parser.add_argument("--lane-limit", type=int, default=50)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--transition-limit", type=int, default=5000)
    parser.add_argument("--chart-sessions", type=int, default=180)
    parser.add_argument("--chart-ticker-limit", type=int, default=24)
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--min-whipsaw-transitions", type=int, default=4)
    parser.add_argument("--min-whipsaw-delta", type=int, default=2)
    parser.add_argument("--ticker", action="append", dest="tickers")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def _label(parameter_set: str | None) -> str:
    return parameter_set or "production"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _table_row(values: list[object]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Dochia Candidate Promotion Review",
        "",
        f"Generated: {payload['generated_at']}",
        f"Baseline: `{payload['baseline_parameter_set']}`",
        f"Candidate: `{payload['candidate_parameter_set']}`",
        f"Transition lookback: {payload['lookback_days']} days",
        f"Chart sessions: {payload['chart_sessions']}",
        "",
        "## Lane Churn",
        "",
        _table_row(["Lane", "Baseline", "Candidate", "Overlap", "Entered", "Exited", "Churn"]),
        _table_row(["---", "---:", "---:", "---:", "---:", "---:", "---:"]),
    ]
    for row in payload["lane_reviews"]:
        lines.append(
            _table_row(
                [
                    row["lane"],
                    row["baseline_count"],
                    row["candidate_count"],
                    row["overlap_count"],
                    ", ".join(row["entered"]) or "-",
                    ", ".join(row["exited"]) or "-",
                    _pct(row["churn_rate"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            "## Whipsaw Pressure",
            "",
            _table_row(["Ticker", "Baseline", "Candidate", "Delta", "Candidate daily", "Latest"]),
            _table_row(["---", "---:", "---:", "---:", "---:", "---"]),
        ]
    )
    for row in payload["whipsaw_clusters"]:
        lines.append(
            _table_row(
                [
                    row["ticker"],
                    row["baseline_transition_count"],
                    row["candidate_transition_count"],
                    f"{row['transition_delta']:+d}",
                    row["candidate_daily_transition_count"],
                    row["latest_candidate_transition_date"] or "-",
                ]
            )
        )
    if not payload["whipsaw_clusters"]:
        lines.append("_No whipsaw clusters crossed the configured thresholds._")

    lines.extend(
        [
            "",
            "## Chart Event Deltas",
            "",
            _table_row(["Ticker", "Baseline daily", "Candidate daily", "Delta", "Candidate-only"]),
            _table_row(["---", "---:", "---:", "---:", "---:"]),
        ]
    )
    for row in payload["chart_event_reviews"]:
        lines.append(
            _table_row(
                [
                    row["ticker"],
                    row["baseline_daily_event_count"],
                    row["candidate_daily_event_count"],
                    f"{row['daily_event_delta']:+d}",
                    row["candidate_only_count"],
                ]
            )
        )
    if not payload["chart_event_reviews"]:
        lines.append("_No chart event deltas found for the reviewed focus tickers._")

    lines.extend(["", "## Candidate-Only Event Samples", ""])
    for row in payload["chart_event_reviews"]:
        if not row["candidate_only_events"]:
            continue
        lines.append(f"### {row['ticker']}")
        for event in row["candidate_only_events"]:
            lines.append(
                "- "
                f"{event['bar_date']} {event['state']} @ {event['trigger_price']}: "
                f"{event['reason']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _fetch_charts(
    conn: psycopg.Connection,
    *,
    tickers: list[str],
    sessions: int,
    parameter_set: str | None,
) -> dict[str, dict[str, Any]]:
    charts: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        chart = fetch_symbol_chart(
            conn,
            ticker=ticker,
            sessions=sessions,
            parameter_set=parameter_set,
        )
        if chart["bars"]:
            charts[ticker] = chart
    return charts


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.lane_limit < 1:
        raise SystemExit("lane-limit must be at least 1")
    if args.lookback_days < 1:
        raise SystemExit("lookback-days must be at least 1")
    if args.chart_ticker_limit < 1:
        raise SystemExit("chart-ticker-limit must be at least 1")

    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        baseline_lanes = fetch_watchlist_candidates(
            conn,
            limit=args.lane_limit,
            parameter_set=args.baseline_parameter_set,
        )
        candidate_lanes = fetch_watchlist_candidates(
            conn,
            limit=args.lane_limit,
            parameter_set=args.candidate_parameter_set,
        )
        lane_reviews = build_lane_reviews(
            baseline_lanes,
            candidate_lanes,
            sample_size=args.sample_size,
        )
        baseline_transitions = fetch_recent_transitions(
            conn,
            limit=args.transition_limit,
            lookback_days=args.lookback_days,
            parameter_set=args.baseline_parameter_set,
        )
        candidate_transitions = fetch_recent_transitions(
            conn,
            limit=args.transition_limit,
            lookback_days=args.lookback_days,
            parameter_set=args.candidate_parameter_set,
        )
        whipsaw_clusters = build_whipsaw_clusters(
            baseline_transitions,
            candidate_transitions,
            min_candidate_transitions=args.min_whipsaw_transitions,
            min_transition_delta=args.min_whipsaw_delta,
            top=args.chart_ticker_limit,
        )
        focus_tickers = (
            [ticker.upper() for ticker in args.tickers]
            if args.tickers
            else focus_tickers_for_chart_review(
                lane_reviews=lane_reviews,
                whipsaw_clusters=whipsaw_clusters,
                candidate_lanes=candidate_lanes,
                limit=args.chart_ticker_limit,
            )
        )
        baseline_charts = _fetch_charts(
            conn,
            tickers=focus_tickers,
            sessions=args.chart_sessions,
            parameter_set=args.baseline_parameter_set,
        )
        candidate_charts = _fetch_charts(
            conn,
            tickers=focus_tickers,
            sessions=args.chart_sessions,
            parameter_set=args.candidate_parameter_set,
        )

    chart_reviews = build_chart_event_reviews(
        baseline_charts,
        candidate_charts,
        sample_size=args.sample_size,
    )
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "baseline_parameter_set": _label(args.baseline_parameter_set),
        "candidate_parameter_set": args.candidate_parameter_set,
        "lookback_days": args.lookback_days,
        "chart_sessions": args.chart_sessions,
        "focus_tickers": focus_tickers,
        "lane_reviews": lane_reviews,
        "whipsaw_clusters": whipsaw_clusters,
        "chart_event_reviews": chart_reviews,
    }


def main() -> None:
    args = parse_args()
    payload = as_jsonable(build_payload(args))
    text = (
        json.dumps(payload, indent=2, sort_keys=True)
        if args.json
        else _render_markdown(payload)  # type: ignore[arg-type]
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
