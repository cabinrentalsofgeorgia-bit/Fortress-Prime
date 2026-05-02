"""Preview Dochia signal-score rows from live EOD bars without writing.

This script is intentionally read-only. It computes the latest deterministic
daily/weekly/monthly Trade Triangle states per ticker and prints the rows that
the next writer step will persist to hedge_fund.signal_scores.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.db_preview import (  # noqa: E402
    SignalScorePreview,
    eod_row_to_bar,
    normalize_psycopg_url,
    preview_from_snapshot,
)
from app.signals.trade_triangles import latest_triangle_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview deterministic Dochia signal-score rows without database writes."
    )
    parser.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Ticker to preview. Repeat for multiple tickers. Defaults to highest-coverage tickers.",
    )
    parser.add_argument(
        "--limit-tickers",
        type=int,
        default=10,
        help="Number of highest-coverage tickers to preview when --ticker is omitted.",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=64,
        help="Minimum EOD bars required for a ticker to be included.",
    )
    parser.add_argument(
        "--as-of",
        type=dt.date.fromisoformat,
        default=None,
        help="Optional YYYY-MM-DD cutoff for bars.",
    )
    parser.add_argument(
        "--parameter-set",
        default=None,
        help="Scoring parameter set name. Defaults to production set.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact table.")
    return parser.parse_args()


def _database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required")
    return normalize_psycopg_url(raw)


def _fetch_parameter_set(conn: psycopg.Connection, name: str | None) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        if name:
            cur.execute(
                """
                SELECT id, name, weight_monthly, weight_weekly, weight_daily, weight_momentum
                FROM hedge_fund.scoring_parameters
                WHERE name = %s
                """,
                (name,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, weight_monthly, weight_weekly, weight_daily, weight_momentum
                FROM hedge_fund.scoring_parameters
                WHERE is_production = TRUE
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        row = cur.fetchone()
    if not row:
        target = name or "production"
        raise RuntimeError(f"scoring parameter set not found: {target}")
    return dict(row)


def _fetch_candidate_tickers(
    conn: psycopg.Connection,
    *,
    limit: int,
    min_bars: int,
    as_of: dt.date | None,
) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker
            FROM hedge_fund.eod_bars
            WHERE (%s::date IS NULL OR bar_date <= %s::date)
            GROUP BY ticker
            HAVING count(*) >= %s
            ORDER BY count(*) DESC, ticker
            LIMIT %s
            """,
            (as_of, as_of, min_bars, limit),
        )
        return [str(row[0]) for row in cur.fetchall()]


def _fetch_bars(conn: psycopg.Connection, ticker: str, as_of: dt.date | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT ticker, bar_date, open, high, low, close, volume
            FROM hedge_fund.eod_bars
            WHERE ticker = %s
              AND (%s::date IS NULL OR bar_date <= %s::date)
            ORDER BY bar_date
            """,
            (ticker, as_of, as_of),
        )
        return [dict(row) for row in cur.fetchall()]


def build_previews(args: argparse.Namespace) -> list[SignalScorePreview]:
    url = _database_url()
    with psycopg.connect(url) as conn:
        conn.execute("SET default_transaction_read_only = on")
        parameter_set = _fetch_parameter_set(conn, args.parameter_set)
        tickers = args.tickers or _fetch_candidate_tickers(
            conn,
            limit=args.limit_tickers,
            min_bars=args.min_bars,
            as_of=args.as_of,
        )

        previews: list[SignalScorePreview] = []
        for ticker in tickers:
            rows = _fetch_bars(conn, ticker.upper(), args.as_of)
            if len(rows) < args.min_bars:
                continue
            bars = [eod_row_to_bar(row) for row in rows]
            snapshot = latest_triangle_snapshot(bars)
            previews.append(
                preview_from_snapshot(
                    snapshot,
                    parameter_set_name=str(parameter_set["name"]),
                    monthly_weight=int(parameter_set["weight_monthly"]),
                    weekly_weight=int(parameter_set["weight_weekly"]),
                    daily_weight=int(parameter_set["weight_daily"]),
                    momentum_weight=int(parameter_set["weight_momentum"]),
                )
            )
        return previews


def _print_table(previews: list[SignalScorePreview]) -> None:
    print("ticker | as_of      | M  W  D | score | events | daily channel")
    print("-------|------------|---------|-------|--------|----------------")
    for item in previews:
        daily_channel = "-"
        if item.daily_channel_low is not None and item.daily_channel_high is not None:
            daily_channel = f"{item.daily_channel_low}..{item.daily_channel_high}"
        print(
            f"{item.ticker:<6} | {item.bar_date} | "
            f"{item.monthly_state:+d} {item.weekly_state:+d} {item.daily_state:+d} | "
            f"{item.composite_score:+5d} | {item.event_count:>6d} | {daily_channel}"
        )


def main() -> None:
    args = parse_args()
    previews = build_previews(args)
    if args.json:
        print(json.dumps([item.as_json_dict() for item in previews], indent=2, sort_keys=True))
    else:
        _print_table(previews)


if __name__ == "__main__":
    main()
