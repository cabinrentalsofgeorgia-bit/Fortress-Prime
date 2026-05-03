"""Read-only parameter sweep for MarketClub daily alert timing."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.calibration_repository import fetch_daily_sweep_results  # noqa: E402
from app.signals.calibration_sweep import DailySweepResult, DailyTriggerMode  # noqa: E402
from app.signals.db_preview import normalize_psycopg_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep daily Trade Triangle event rules against MarketClub daily alerts."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--lookback-min", type=int, default=2)
    parser.add_argument("--lookback-max", type=int, default=10)
    parser.add_argument(
        "--trigger-mode",
        action="append",
        choices=["close", "range"],
        default=None,
        help="Can be passed more than once. Defaults to close and range.",
    )
    parser.add_argument("--event-window-days", type=int, default=3)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required")
    return normalize_psycopg_url(raw)


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _print_table(results: list[DailySweepResult], *, top: int) -> None:
    if not results:
        print("No sweep results.")
        return

    baseline = next(
        (
            result
            for result in results
            if result.lookback_sessions == 3 and result.trigger_mode == "close"
        ),
        None,
    )
    print("Daily MarketClub event sweep")
    print(
        "observations="
        f"{results[0].total_observations} covered={results[0].covered_observations} "
        f"ranked_by=exact_event_f1"
    )
    if baseline is not None:
        print(
            "current baseline="
            f"lookback=3 mode=close f1={_pct(baseline.exact_event_f1)} "
            f"precision={_pct(baseline.exact_event_precision)} "
            f"recall={_pct(baseline.exact_event_recall)}"
        )
    print()
    print(
        "rank | lookback | mode  | f1      | precision | recall   | +/-3d recall | "
        "carried | generated | no_event | opposite"
    )
    print(
        "-----|----------|-------|---------|-----------|----------|--------------|"
        "---------|-----------|----------|---------"
    )
    for rank, result in enumerate(results[:top], start=1):
        print(
            f"{rank:>4} | {result.lookback_sessions:>8} | "
            f"{result.trigger_mode:<5} | {_pct(result.exact_event_f1):>7} | "
            f"{_pct(result.exact_event_precision):>9} | "
            f"{_pct(result.exact_event_recall):>8} | "
            f"{_pct(result.window_event_recall):>12} | "
            f"{_pct(result.carried_state_accuracy):>7} | "
            f"{result.generated_events:>9} | "
            f"{result.no_event_observations:>8} | "
            f"{result.opposite_event_observations:>8}"
        )


def main() -> None:
    args = parse_args()
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit("since cannot be after until")
    if args.lookback_min < 1:
        raise SystemExit("lookback-min must be at least 1")
    if args.lookback_min > args.lookback_max:
        raise SystemExit("lookback-min cannot exceed lookback-max")
    if args.top < 1:
        raise SystemExit("top must be at least 1")

    trigger_modes: list[DailyTriggerMode] = args.trigger_mode or ["close", "range"]
    lookbacks = list(range(args.lookback_min, args.lookback_max + 1))
    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        results = fetch_daily_sweep_results(
            conn,
            since=args.since,
            until=args.until,
            ticker=args.ticker,
            lookbacks=lookbacks,
            trigger_modes=trigger_modes,
            event_window_days=args.event_window_days,
        )

    if args.json:
        print(json.dumps([result.as_json_dict() for result in results], indent=2, sort_keys=True))
    else:
        _print_table(results, top=args.top)


if __name__ == "__main__":
    main()
