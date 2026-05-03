#!/usr/bin/env python3
"""Review forward returns and whipsaw clusters for Dochia daily signals."""

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
from app.signals.calibration_sweep import generated_daily_event_history  # noqa: E402
from app.signals.guardrail_sweep import (  # noqa: E402
    GuardedRangeCandidate,
    generated_guarded_range_event_history,
)
from app.signals.outcome_review import (  # noqa: E402
    build_ticker_whipsaw_outcomes,
    events_from_histories,
    summarize_forward_returns,
)
from scripts.sweep_daily_signal_parameters import _database_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review forward returns and whipsaw clusters for daily signal candidates."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--whipsaw-window-sessions", type=int, default=5)
    parser.add_argument("--whipsaw-outcome-horizon", type=int, default=5)
    parser.add_argument("--top-whipsaws", type=int, default=15)
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
    for horizon in args.horizon or [5, 10, 20]:
        if horizon < 1:
            raise SystemExit("horizon must be at least 1")
    if args.whipsaw_window_sessions < 1:
        raise SystemExit("whipsaw-window-sessions must be at least 1")
    if args.whipsaw_outcome_horizon < 1:
        raise SystemExit("whipsaw-outcome-horizon must be at least 1")
    if args.top_whipsaws < 1:
        raise SystemExit("top-whipsaws must be at least 1")


def _histories_for_mode(
    bars_by_ticker: dict[str, list[Any]],
    *,
    mode: str,
) -> dict[str, Any]:
    histories: dict[str, Any] = {}
    for ticker, bars in bars_by_ticker.items():
        if mode == "production_close":
            history = generated_daily_event_history(
                bars,
                lookback_sessions=3,
                trigger_mode="close",
            )
        elif mode == "v0_2_raw_range":
            history = generated_guarded_range_event_history(
                bars,
                candidate=GuardedRangeCandidate(lookback_sessions=3),
            )
        else:
            raise ValueError(f"unknown mode: {mode}")
        if history is not None:
            histories[ticker] = history
    return histories


def _render_outcomes(rule_name: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = []
    for row in rows:
        lines.append(
            _table_row(
                [
                    rule_name,
                    row["horizon_sessions"],
                    row["evaluated_events"],
                    _pct(row["win_rate"]),
                    _signed_pct(row["average_directional_return"]),
                    _signed_pct(row["median_directional_return"]),
                    _signed_pct(row["p25_directional_return"]),
                    _signed_pct(row["p75_directional_return"]),
                ]
            )
        )
    return lines


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Dochia v0.3 Return Outcome Review",
        "",
        f"Generated: {payload['generated_at']}",
        f"Scope: ticker={payload['ticker'] or 'all'} since={payload['since'] or 'beginning'} until={payload['until'] or 'latest'}",
        f"Whipsaw window: {payload['whipsaw_window_sessions']} sessions",
        "",
        "## Forward Directional Returns",
        "",
        _table_row(
            [
                "Rule",
                "Horizon",
                "Events",
                "Win rate",
                "Average",
                "Median",
                "P25",
                "P75",
            ]
        ),
        _table_row(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]),
    ]
    lines.extend(_render_outcomes("production close", payload["production_close"]["outcomes"]))
    lines.extend(_render_outcomes("v0.2 raw range", payload["v0_2_raw_range"]["outcomes"]))

    lines.extend(
        [
            "",
            "## v0.2 Whipsaw Clusters",
            "",
            _table_row(
                [
                    "Ticker",
                    "Events",
                    "Whipsaws",
                    "Rate",
                    "5-session events",
                    "Avg 5-session return",
                    "Latest",
                ]
            ),
            _table_row(["---", "---:", "---:", "---:", "---:", "---:", "---"]),
        ]
    )
    for row in payload["v0_2_raw_range"]["whipsaw_clusters"]:
        lines.append(
            _table_row(
                [
                    row["ticker"],
                    row["event_count"],
                    row["whipsaw_count"],
                    _pct(row["whipsaw_rate"]),
                    row["evaluated_horizon_events"],
                    _signed_pct(row["average_directional_return"]),
                    row["latest_whipsaw_date"] or "-",
                ]
            )
        )
    if not payload["v0_2_raw_range"]["whipsaw_clusters"]:
        lines.append("_No whipsaw clusters crossed the configured window._")

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "Do not promote or suppress v0.2 only from alert-match F1. Use this return-outcome layer with the promotion-review churn packet: candidates must preserve alert quality, reduce whipsaw clusters, and avoid degrading forward directional returns.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _rule_payload(
    bars_by_ticker: dict[str, list[Any]],
    *,
    mode: str,
    horizons: list[int],
    since: dt.date | None,
    until: dt.date | None,
    whipsaw_window_sessions: int,
    whipsaw_outcome_horizon: int,
    top_whipsaws: int,
) -> dict[str, Any]:
    histories = _histories_for_mode(bars_by_ticker, mode=mode)
    events = events_from_histories(histories, bars_by_ticker, since=since, until=until)
    outcomes = summarize_forward_returns(events, bars_by_ticker, horizons=horizons)
    whipsaws = build_ticker_whipsaw_outcomes(
        events,
        bars_by_ticker,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=whipsaw_outcome_horizon,
        top=top_whipsaws,
    )
    return {
        "event_count": len(events),
        "outcomes": [row.as_json_dict() for row in outcomes],
        "whipsaw_clusters": [row.as_json_dict() for row in whipsaws],
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    horizons = args.horizon or [5, 10, 20]
    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        _, bars_by_ticker = fetch_daily_sweep_inputs(
            conn,
            since=args.since,
            until=args.until,
            ticker=args.ticker,
        )

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "since": args.since.isoformat() if args.since else None,
        "until": args.until.isoformat() if args.until else None,
        "ticker": args.ticker.upper() if args.ticker else None,
        "horizons": horizons,
        "whipsaw_window_sessions": args.whipsaw_window_sessions,
        "production_close": _rule_payload(
            bars_by_ticker,
            mode="production_close",
            horizons=horizons,
            since=args.since,
            until=args.until,
            whipsaw_window_sessions=args.whipsaw_window_sessions,
            whipsaw_outcome_horizon=args.whipsaw_outcome_horizon,
            top_whipsaws=args.top_whipsaws,
        ),
        "v0_2_raw_range": _rule_payload(
            bars_by_ticker,
            mode="v0_2_raw_range",
            horizons=horizons,
            since=args.since,
            until=args.until,
            whipsaw_window_sessions=args.whipsaw_window_sessions,
            whipsaw_outcome_horizon=args.whipsaw_outcome_horizon,
            top_whipsaws=args.top_whipsaws,
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
