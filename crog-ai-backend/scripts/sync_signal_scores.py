"""Dry-run or sync latest deterministic Dochia signal scores.

Default mode is read-only and prints the rows that would be written. Add
--execute to upsert latest rows into hedge_fund.signal_scores.
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
from app.signals.db_sync import UPSERT_SIGNAL_SCORE_SQL, signal_score_params  # noqa: E402
from app.signals.trade_triangles import latest_triangle_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or upsert latest deterministic Dochia signal scores."
    )
    parser.add_argument("--ticker", action="append", dest="tickers")
    parser.add_argument("--limit-tickers", type=int, default=10)
    parser.add_argument("--min-bars", type=int, default=64)
    parser.add_argument("--max-stale-days", type=int, default=5)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--parameter-set", default=None)
    parser.add_argument(
        "--daily-trigger-mode",
        choices=["close", "range"],
        default=None,
        help=(
            "Daily trigger mode. Defaults to close, except the "
            "dochia_v0_2_range_daily candidate resolves to range."
        ),
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--display-limit", type=int, default=120)
    parser.add_argument("--json", action="store_true")
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
                SELECT
                    id,
                    name,
                    monthly_lookback_days,
                    weekly_lookback_days,
                    daily_lookback_days,
                    weight_monthly,
                    weight_weekly,
                    weight_daily,
                    weight_momentum
                FROM hedge_fund.scoring_parameters
                WHERE name = %s
                """,
                (name,),
            )
        else:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    monthly_lookback_days,
                    weekly_lookback_days,
                    daily_lookback_days,
                    weight_monthly,
                    weight_weekly,
                    weight_daily,
                    weight_momentum
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


def _fetch_reference_date(conn: psycopg.Connection, as_of: dt.date | None) -> dt.date:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT max(bar_date)
            FROM hedge_fund.eod_bars
            WHERE (%s::date IS NULL OR bar_date <= %s::date)
            """,
            (as_of, as_of),
        )
        value = cur.fetchone()[0]
    if value is None:
        target = as_of.isoformat() if as_of else "latest"
        raise RuntimeError(f"no EOD bars found for reference date: {target}")
    return value


def _fresh_cutoff(reference_date: dt.date, max_stale_days: int) -> dt.date:
    return reference_date - dt.timedelta(days=max_stale_days)


def _is_fresh_enough(
    bar_date: dt.date,
    *,
    reference_date: dt.date,
    max_stale_days: int,
) -> bool:
    return bar_date >= _fresh_cutoff(reference_date, max_stale_days)


def _fetch_candidate_tickers(
    conn: psycopg.Connection,
    *,
    limit: int,
    min_bars: int,
    as_of: dt.date | None,
    include_stale: bool,
    reference_date: dt.date,
    max_stale_days: int,
) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH candidate_bars AS (
                SELECT ticker, count(*) AS bar_count, max(bar_date) AS latest_bar_date
                FROM hedge_fund.eod_bars
                WHERE (%s::date IS NULL OR bar_date <= %s::date)
                GROUP BY ticker
            )
            SELECT ticker
            FROM candidate_bars
            WHERE bar_count >= %s
              AND (
                  %s
                  OR latest_bar_date >= (%s::date - %s::int)
              )
            ORDER BY bar_count DESC, ticker
            LIMIT %s
            """,
            (
                as_of,
                as_of,
                min_bars,
                include_stale,
                reference_date,
                max_stale_days,
                limit,
            ),
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


def _resolve_daily_trigger_mode(parameter_set_name: str, explicit_mode: str | None) -> str:
    if explicit_mode:
        return explicit_mode
    if parameter_set_name == "dochia_v0_2_range_daily":
        return "range"
    return "close"


def build_previews_and_parameter_set(
    args: argparse.Namespace,
    conn: psycopg.Connection,
) -> tuple[list[SignalScorePreview], dict[str, Any]]:
    parameter_set = _fetch_parameter_set(conn, args.parameter_set)
    daily_trigger_mode = _resolve_daily_trigger_mode(
        str(parameter_set["name"]),
        args.daily_trigger_mode,
    )
    reference_date = _fetch_reference_date(conn, args.as_of)
    tickers = args.tickers or _fetch_candidate_tickers(
        conn,
        limit=args.limit_tickers,
        min_bars=args.min_bars,
        as_of=args.as_of,
        include_stale=args.include_stale,
        reference_date=reference_date,
        max_stale_days=args.max_stale_days,
    )

    previews: list[SignalScorePreview] = []
    for ticker in tickers:
        rows = _fetch_bars(conn, ticker.upper(), args.as_of)
        if len(rows) < args.min_bars:
            continue
        bars = [eod_row_to_bar(row) for row in rows]
        snapshot = latest_triangle_snapshot(
            bars,
            daily_trigger_mode=daily_trigger_mode,
            daily_lookback_sessions=int(parameter_set["daily_lookback_days"]),
            weekly_lookback_sessions=int(parameter_set["weekly_lookback_days"]),
            monthly_lookback_sessions=int(parameter_set["monthly_lookback_days"]),
        )
        if not args.include_stale and not _is_fresh_enough(
            snapshot.bar_date,
            reference_date=reference_date,
            max_stale_days=args.max_stale_days,
        ):
            continue
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
    return previews, parameter_set


def _print_table(
    previews: list[SignalScorePreview],
    *,
    execute: bool,
    display_limit: int,
) -> None:
    mode = "EXECUTE" if execute else "DRY RUN"
    print(f"{mode}: {len(previews)} latest signal score rows")
    print("ticker | as_of      | M  W  D | score | events")
    print("-------|------------|---------|-------|-------")
    for item in previews[:display_limit]:
        print(
            f"{item.ticker:<6} | {item.bar_date} | "
            f"{item.monthly_state:+d} {item.weekly_state:+d} {item.daily_state:+d} | "
            f"{item.composite_score:+5d} | {item.event_count:>5d}"
        )
    hidden = len(previews) - display_limit
    if hidden > 0:
        print(f"... {hidden} more rows hidden; use --json for full output")


def _write_previews(
    conn: psycopg.Connection,
    previews: list[SignalScorePreview],
    parameter_set: dict[str, Any],
) -> int:
    with conn.cursor() as cur:
        for preview in previews:
            cur.execute(
                UPSERT_SIGNAL_SCORE_SQL,
                signal_score_params(preview, parameter_set_id=parameter_set["id"]),
            )
    return len(previews)


def main() -> None:
    args = parse_args()
    url = _database_url()
    with psycopg.connect(url) as conn:
        if not args.execute:
            conn.execute("SET default_transaction_read_only = on")

        previews, parameter_set = build_previews_and_parameter_set(args, conn)
        if args.execute:
            written = _write_previews(conn, previews, parameter_set)
            conn.commit()
        else:
            written = 0

    if args.json:
        payload = {
            "mode": "execute" if args.execute else "dry_run",
            "rows_previewed": len(previews),
            "rows_written": written,
            "previews": [item.as_json_dict() for item in previews],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_table(previews, execute=args.execute, display_limit=args.display_limit)
        if args.execute:
            print(f"rows_written={written}")
        else:
            print("rows_written=0")


if __name__ == "__main__":
    main()
