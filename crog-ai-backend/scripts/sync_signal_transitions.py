"""Dry-run or sync recent deterministic Dochia signal transition events."""

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

from app.signals.db_preview import (  # noqa: E402
    SignalTransitionPreview,
    eod_row_to_bar,
    transition_previews_from_snapshot,
)
from app.signals.db_sync import (  # noqa: E402
    INSERT_SIGNAL_TRANSITION_SQL,
    signal_transition_params,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or insert recent deterministic Dochia signal transitions."
    )
    parser.add_argument("--ticker", action="append", dest="tickers")
    parser.add_argument("--limit-tickers", type=int, default=10)
    parser.add_argument("--min-bars", type=int, default=64)
    parser.add_argument("--max-stale-days", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
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


def _effective_since(reference_date: dt.date, args: argparse.Namespace) -> dt.date:
    if args.since is not None:
        return args.since
    return reference_date - dt.timedelta(days=args.lookback_days)


def build_transition_previews_and_parameter_set(
    args: argparse.Namespace,
    conn: psycopg.Connection,
) -> tuple[list[SignalTransitionPreview], dict[str, Any], dt.date]:
    parameter_set = _fetch_parameter_set(conn, args.parameter_set)
    daily_trigger_mode = _resolve_daily_trigger_mode(
        str(parameter_set["name"]),
        args.daily_trigger_mode,
    )
    reference_date = _fetch_reference_date(conn, args.as_of)
    since = _effective_since(reference_date, args)
    tickers = args.tickers or _fetch_candidate_tickers(
        conn,
        limit=args.limit_tickers,
        min_bars=args.min_bars,
        as_of=args.as_of,
        include_stale=args.include_stale,
        reference_date=reference_date,
        max_stale_days=args.max_stale_days,
    )

    previews: list[SignalTransitionPreview] = []
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
        previews.extend(
            transition_previews_from_snapshot(
                snapshot,
                parameter_set_name=str(parameter_set["name"]),
                monthly_weight=int(parameter_set["weight_monthly"]),
                weekly_weight=int(parameter_set["weight_weekly"]),
                daily_weight=int(parameter_set["weight_daily"]),
                momentum_weight=int(parameter_set["weight_momentum"]),
                since=since,
            )
        )
    return previews, parameter_set, since


def _print_table(
    previews: list[SignalTransitionPreview],
    *,
    execute: bool,
    since: dt.date,
    display_limit: int,
) -> None:
    mode = "EXECUTE" if execute else "DRY RUN"
    print(f"{mode}: {len(previews)} signal transition rows since {since.isoformat()}")
    print("ticker | to_date    | type              | score")
    print("-------|------------|-------------------|------------")
    for item in previews[:display_limit]:
        print(
            f"{item.ticker:<6} | {item.to_bar_date} | "
            f"{item.transition_type:<17} | {item.from_score:+4d}->{item.to_score:+4d}"
        )
    hidden = len(previews) - display_limit
    if hidden > 0:
        print(f"... {hidden} more rows hidden; use --json for full output")


def _write_previews(
    conn: psycopg.Connection,
    previews: list[SignalTransitionPreview],
    parameter_set: dict[str, Any],
) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for preview in previews:
            cur.execute(
                INSERT_SIGNAL_TRANSITION_SQL,
                signal_transition_params(preview, parameter_set_id=parameter_set["id"]),
            )
            inserted += cur.rowcount
    return inserted


def main() -> None:
    args = parse_args()
    url = _database_url()
    with psycopg.connect(url) as conn:
        if not args.execute:
            conn.execute("SET default_transaction_read_only = on")

        previews, parameter_set, since = build_transition_previews_and_parameter_set(
            args, conn
        )
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
            "since": since.isoformat(),
            "previews": [item.as_json_dict() for item in previews],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_table(
            previews,
            execute=args.execute,
            since=since,
            display_limit=args.display_limit,
        )
        print(f"rows_written={written}")


if __name__ == "__main__":
    main()
