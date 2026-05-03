"""Read-only daily signal calibration report for Dochia vs MarketClub."""

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

from app.signals.calibration_repository import fetch_daily_calibration  # noqa: E402
from app.signals.db_preview import normalize_psycopg_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare generated Dochia daily state to historical MarketClub daily alerts."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--parameter-set", default=None)
    parser.add_argument("--top-tickers", type=int, default=20)
    parser.add_argument("--event-window-days", type=int, default=3)
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


def _number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _print_table(payload: dict[str, object]) -> None:
    print("Daily MarketClub calibration")
    print(f"parameter_set={payload['parameter_set_name']}")
    print(f"window={payload['since'] or 'start'}..{payload['until'] or 'latest'}")
    print(
        "observations="
        f"{payload['total_observations']} covered={payload['covered_observations']} "
        f"exact_bars={payload['exact_bar_observations']}"
    )
    print(
        "accuracy="
        f"{_pct(payload['accuracy'])} coverage={_pct(payload['coverage_rate'])} "
        f"score_mae={_number(payload['score_mae'])} score_rmse={_number(payload['score_rmse'])}"
    )
    print(
        "green precision/recall="
        f"{_pct(payload['green_precision'])}/{_pct(payload['green_recall'])} "
        "red precision/recall="
        f"{_pct(payload['red_precision'])}/{_pct(payload['red_recall'])}"
    )
    print(
        "event exact/window="
        f"{_pct(payload['exact_event_accuracy'])}/"
        f"{_pct(payload['window_event_accuracy'])} "
        f"window_days={payload['event_window_days']} "
        f"no_event={payload['no_generated_event_observations']} "
        f"opposite_event={payload['opposite_generated_event_observations']}"
    )
    print()
    print("confusion")
    print(json.dumps(payload["confusion"], indent=2, sort_keys=True))
    print()
    print("event confusion")
    print(json.dumps(payload["event_confusion"], indent=2, sort_keys=True))
    print()
    print("ticker | obs | covered | exact | matches | accuracy | score_mae")
    print("-------|-----|---------|-------|---------|----------|----------")
    for row in payload["top_tickers"]:
        print(
            f"{row['ticker']:<6} | {row['observations']:>3} | "
            f"{row['covered_observations']:>7} | {row['exact_bar_observations']:>5} | "
            f"{row['matches']:>7} | {_pct(row['accuracy']):>8} | {_number(row['score_mae']):>8}"
        )


def main() -> None:
    args = parse_args()
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit("since cannot be after until")

    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        result = fetch_daily_calibration(
            conn,
            since=args.since,
            until=args.until,
            ticker=args.ticker,
            parameter_set=args.parameter_set,
            top_tickers=args.top_tickers,
            event_window_days=args.event_window_days,
        )

    payload = result.as_json_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_table(payload)


if __name__ == "__main__":
    main()
