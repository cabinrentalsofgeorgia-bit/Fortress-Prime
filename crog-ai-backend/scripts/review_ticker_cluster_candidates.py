#!/usr/bin/env python3
"""Research ticker-cluster cooldown/exclusion candidates for v0.2 whipsaws."""

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

from app.signals.calibration_repository import fetch_daily_sweep_inputs  # noqa: E402
from app.signals.guardrail_sweep import (  # noqa: E402
    GuardedRangeCandidate,
    generated_guarded_range_event_history,
)
from app.signals.outcome_review import (  # noqa: E402
    TickerClusterCandidate,
    build_ticker_whipsaw_outcomes,
    evaluate_event_histories,
    events_from_histories,
    review_ticker_cluster_candidate,
    summarize_forward_returns,
)
from scripts.sweep_daily_signal_parameters import _database_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review ticker-cluster cooldown/exclusion candidates for v0.2 whipsaws."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--cluster-since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--cluster-until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--cluster-size", action="append", type=int, default=None)
    parser.add_argument("--cooldown-sessions", action="append", type=int, default=None)
    parser.add_argument("--include-exclude", action="store_true")
    parser.add_argument("--event-window-days", type=int, default=3)
    parser.add_argument("--outcome-horizon", type=int, default=5)
    parser.add_argument("--whipsaw-window-sessions", type=int, default=5)
    parser.add_argument("--top-whipsaws", type=int, default=30)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.2f}%"


def _table_row(values: list[object]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _validate_args(args: argparse.Namespace) -> None:
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit("since cannot be after until")
    if (
        args.cluster_since is not None
        and args.cluster_until is not None
        and args.cluster_since > args.cluster_until
    ):
        raise SystemExit("cluster-since cannot be after cluster-until")
    for cluster_size in args.cluster_size or [5, 10, 15]:
        if cluster_size < 1:
            raise SystemExit("cluster-size must be at least 1")
    for cooldown in args.cooldown_sessions or [5, 10, 20]:
        if cooldown < 1:
            raise SystemExit("cooldown-sessions must be at least 1")
    if args.event_window_days < 0:
        raise SystemExit("event-window-days must be non-negative")
    if args.outcome_horizon < 1:
        raise SystemExit("outcome-horizon must be at least 1")
    if args.whipsaw_window_sessions < 1:
        raise SystemExit("whipsaw-window-sessions must be at least 1")
    if args.top_whipsaws < 1:
        raise SystemExit("top-whipsaws must be at least 1")
    if args.top < 1:
        raise SystemExit("top must be at least 1")


def _raw_range_histories(bars_by_ticker: dict[str, list[Any]]) -> dict[str, Any]:
    histories: dict[str, Any] = {}
    for ticker, bars in bars_by_ticker.items():
        history = generated_guarded_range_event_history(
            bars,
            candidate=GuardedRangeCandidate(lookback_sessions=3),
        )
        if history is not None:
            histories[ticker] = history
    return histories


def _candidate_grid(args: argparse.Namespace) -> list[TickerClusterCandidate]:
    cluster_sizes = args.cluster_size or [5, 10, 15]
    cooldowns = args.cooldown_sessions or [5, 10, 20]
    candidates = [
        TickerClusterCandidate(
            cluster_size=cluster_size,
            mode="cooldown",
            cooldown_sessions=cooldown,
        )
        for cluster_size in cluster_sizes
        for cooldown in cooldowns
    ]
    if args.include_exclude:
        candidates.extend(
            TickerClusterCandidate(cluster_size=cluster_size, mode="exclude")
            for cluster_size in cluster_sizes
        )
    return candidates


def _candidate_label(row: dict[str, Any]) -> str:
    candidate = row["candidate"]
    if candidate["mode"] == "exclude":
        return f"top {candidate['cluster_size']} exclude"
    return f"top {candidate['cluster_size']} cooldown {candidate['cooldown_sessions']}"


def _render_candidate_row(row: dict[str, Any], rank: int | str) -> str:
    alert = row["alert_match"]
    outcome = row["outcome_5_session"]
    return _table_row(
        [
            rank,
            _candidate_label(row),
            alert["generated_events"],
            _pct(row["generated_event_reduction"]),
            _pct(alert["exact_event_f1"]),
            _pct(alert["exact_event_precision"]),
            _pct(alert["exact_event_recall"]),
            _pct(alert["window_event_recall"]),
            _pct(outcome["win_rate"]),
            _signed_pct(outcome["average_directional_return"]),
            row["top_whipsaw_count"],
            ", ".join(row["top_whipsaw_tickers"][:5]),
        ]
    )


def _append_candidate_table(lines: list[str], rows: list[dict[str, Any]], *, prefix: str = "") -> None:
    lines.extend(
        [
            _table_row(
                [
                    "Rank",
                    "Candidate",
                    "Events",
                    "Event reduction",
                    "F1",
                    "Precision",
                    "Recall",
                    "±3d recall",
                    "5d win",
                    "Avg 5d",
                    "Top whipsaws",
                    "Top whipsaw tickers",
                ]
            ),
            _table_row(
                [
                    "---:",
                    "---",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---",
                ]
            ),
        ]
    )
    for rank, row in enumerate(rows, start=1):
        lines.append(_render_candidate_row(row, f"{prefix}{rank}"))


def _render_markdown(payload: dict[str, Any]) -> str:
    raw_alert = payload["raw_range_baseline"]["alert_match"]
    raw_outcome = payload["raw_range_baseline"]["outcome_5_session"]
    recommendation = payload["recommendation"]
    lines = [
        "# Dochia v0.3 Ticker-Cluster Candidate Review",
        "",
        f"Generated: {payload['generated_at']}",
        f"Scope: ticker={payload['ticker'] or 'all'} since={payload['since'] or 'beginning'} until={payload['until'] or 'latest'}",
        f"Cluster source: top {payload['top_whipsaws']} v0.2 whipsaw tickers over {payload['whipsaw_window_sessions']} sessions; since={payload['cluster_since'] or 'beginning'} until={payload['cluster_until'] or 'latest'}",
        "",
        "## Raw v0.2 Baseline",
        "",
        _table_row(
            [
                "Events",
                "F1",
                "Precision",
                "Recall",
                "±3d recall",
                "5d win",
                "Avg 5d",
                "Top whipsaw count",
            ]
        ),
        _table_row(["---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]),
        _table_row(
            [
                raw_alert["generated_events"],
                _pct(raw_alert["exact_event_f1"]),
                _pct(raw_alert["exact_event_precision"]),
                _pct(raw_alert["exact_event_recall"]),
                _pct(raw_alert["window_event_recall"]),
                _pct(raw_outcome["win_rate"]),
                _signed_pct(raw_outcome["average_directional_return"]),
                payload["raw_range_baseline"]["top_whipsaw_count"],
            ]
        ),
        "",
        "Top cluster tickers: " + ", ".join(payload["cluster_tickers"][:15]),
        "",
        "## Quality-Preserving Candidates",
        "",
    ]
    if payload["quality_preserving_results"]:
        _append_candidate_table(lines, payload["quality_preserving_results"])
    else:
        lines.append("_No candidates preserved at least 95% of raw-range F1._")

    lines.extend(["", "## Best Event-Reduction Candidates", ""])
    _append_candidate_table(lines, payload["best_reduction_results"], prefix="R")

    lines.extend(["", "## Recommendation", ""])
    if recommendation is None:
        lines.append(
            "No ticker-cluster candidate cleared the default gate: at least 95% of raw-range F1, at least 5% event reduction, fewer top whipsaws, and no worse 5-session average directional return. Keep v0.2 candidate-only."
        )
    else:
        lines.extend(
            [
                "Use this as the next non-production v0.3 candidate only after a chronological holdout check:",
                "",
            ]
        )
        _append_candidate_table(lines, [recommendation])
    return "\n".join(lines).rstrip() + "\n"


def _review_sort_key(row: dict[str, Any]) -> tuple[float, float, float]:
    return (
        row["generated_event_reduction"] or 0,
        row["alert_match"]["exact_event_f1"] or 0,
        row["outcome_5_session"]["average_directional_return"] or 0,
    )


def _pick_recommendation(
    rows: list[dict[str, Any]],
    *,
    raw_f1: float,
    raw_avg_return: float,
    raw_whipsaw_count: int,
) -> dict[str, Any] | None:
    eligible = [
        row
        for row in rows
        if (row["alert_match"]["exact_event_f1"] or 0) >= raw_f1 * 0.95
        and (row["generated_event_reduction"] or 0) >= 0.05
        and row["top_whipsaw_count"] < raw_whipsaw_count
        and (row["outcome_5_session"]["average_directional_return"] or 0) >= raw_avg_return
    ]
    if not eligible:
        return None
    eligible.sort(key=_review_sort_key, reverse=True)
    return eligible[0]


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        observations, bars_by_ticker = fetch_daily_sweep_inputs(
            conn,
            since=None,
            until=args.until,
            ticker=args.ticker,
        )

    eval_observations = [
        observation
        for observation in observations
        if (args.since is None or observation.trading_day >= args.since)
        and (args.until is None or observation.trading_day <= args.until)
    ]
    raw_histories = _raw_range_histories(bars_by_ticker)
    raw_alert = evaluate_event_histories(
        eval_observations,
        raw_histories,
        event_window_days=args.event_window_days,
    )
    raw_events = events_from_histories(raw_histories, bars_by_ticker, since=args.since, until=args.until)
    raw_outcome = summarize_forward_returns(
        raw_events,
        bars_by_ticker,
        horizons=[args.outcome_horizon],
    )[0]
    eval_whipsaws = build_ticker_whipsaw_outcomes(
        raw_events,
        bars_by_ticker,
        whipsaw_window_sessions=args.whipsaw_window_sessions,
        outcome_horizon_sessions=args.outcome_horizon,
        top=args.top_whipsaws,
    )
    cluster_events = events_from_histories(
        raw_histories,
        bars_by_ticker,
        since=args.cluster_since,
        until=args.cluster_until,
    )
    cluster_whipsaws = build_ticker_whipsaw_outcomes(
        cluster_events,
        bars_by_ticker,
        whipsaw_window_sessions=args.whipsaw_window_sessions,
        outcome_horizon_sessions=args.outcome_horizon,
        top=args.top_whipsaws,
    )
    cluster_tickers = [row.ticker for row in cluster_whipsaws]
    candidate_rows = [
        review_ticker_cluster_candidate(
            eval_observations,
            raw_histories,
            bars_by_ticker,
            cluster_tickers=cluster_tickers,
            candidate=candidate,
            raw_generated_events=raw_alert.generated_events,
            event_window_days=args.event_window_days,
            whipsaw_window_sessions=args.whipsaw_window_sessions,
            outcome_horizon_sessions=args.outcome_horizon,
            top_whipsaws=args.top_whipsaws,
            since=args.since,
            until=args.until,
        ).as_json_dict()
        for candidate in _candidate_grid(args)
    ]
    raw_f1 = raw_alert.exact_event_f1 or 0
    raw_avg_return = raw_outcome.average_directional_return or 0
    raw_whipsaw_count = sum(row.whipsaw_count for row in eval_whipsaws)
    quality_preserving = [
        row
        for row in candidate_rows
        if (row["alert_match"]["exact_event_f1"] or 0) >= raw_f1 * 0.95
    ]
    quality_preserving.sort(key=_review_sort_key, reverse=True)
    best_reduction = sorted(candidate_rows, key=_review_sort_key, reverse=True)
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "since": args.since.isoformat() if args.since else None,
        "until": args.until.isoformat() if args.until else None,
        "cluster_since": args.cluster_since.isoformat() if args.cluster_since else None,
        "cluster_until": args.cluster_until.isoformat() if args.cluster_until else None,
        "ticker": args.ticker.upper() if args.ticker else None,
        "top_whipsaws": args.top_whipsaws,
        "whipsaw_window_sessions": args.whipsaw_window_sessions,
        "cluster_tickers": cluster_tickers,
        "raw_range_baseline": {
            "alert_match": raw_alert.as_json_dict(),
            "outcome_5_session": raw_outcome.as_json_dict(),
            "top_whipsaw_count": raw_whipsaw_count,
        },
        "quality_preserving_results": quality_preserving[: args.top],
        "best_reduction_results": best_reduction[: args.top],
        "recommendation": _pick_recommendation(
            candidate_rows,
            raw_f1=raw_f1,
            raw_avg_return=raw_avg_return,
            raw_whipsaw_count=raw_whipsaw_count,
        ),
    }


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    text = (
        json.dumps(payload, indent=2, sort_keys=True)
        if args.json
        else _render_markdown(payload)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
