"""Read-only promotion review for a non-production Dochia signal candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.chart_repository import fetch_symbol_chart  # noqa: E402
from app.signals.db_preview import normalize_psycopg_url  # noqa: E402

PRODUCTION_PARAMETER_SET = "dochia_v0_estimated"
DEFAULT_CANDIDATE_PARAMETER_SET = "dochia_v0_2_range_daily"
REENTRY_TRANSITIONS = {"exit_to_reentry", "breakout_bullish"}


@dataclass(frozen=True, slots=True)
class LaneDelta:
    lane: str
    production_count: int
    candidate_count: int
    entered: list[str]
    exited: list[str]


@dataclass(frozen=True, slots=True)
class ScoreDelta:
    ticker: str
    production_score: int
    candidate_score: int
    delta: int
    production_daily_state: int
    candidate_daily_state: int


@dataclass(frozen=True, slots=True)
class WhipsawRow:
    ticker: str
    production_transitions: int
    candidate_transitions: int
    delta: int
    latest_candidate_transition: str | None
    latest_candidate_bar_date: dt.date | None


@dataclass(frozen=True, slots=True)
class ChartReviewRow:
    ticker: str
    production_daily_events: int
    candidate_daily_events: int
    candidate_latest_daily_state: str | None
    candidate_latest_daily_date: dt.date | None
    candidate_latest_trigger_price: Decimal | None
    candidate_latest_reason: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review whether a non-production Dochia signal candidate is promotion-ready."
    )
    parser.add_argument("--candidate-parameter-set", default=DEFAULT_CANDIDATE_PARAMETER_SET)
    parser.add_argument("--production-parameter-set", default=PRODUCTION_PARAMETER_SET)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--chart-sessions", type=int, default=180)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required")
    return normalize_psycopg_url(raw)


def _latest_scores(conn: psycopg.Connection, parameter_set: str) -> dict[str, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (v.ticker)
                v.ticker,
                v.bar_date,
                v.monthly_state,
                v.weekly_state,
                v.daily_state,
                v.momentum_state,
                v.composite_score
            FROM hedge_fund.v_signal_scores_composite v
            JOIN hedge_fund.scoring_parameters p ON p.id = v.parameter_set_id
            WHERE p.name = %(parameter_set)s
              AND p.is_active = TRUE
            ORDER BY v.ticker, v.bar_date DESC, v.computed_at DESC
            """,
            {"parameter_set": parameter_set},
        )
        return {str(row["ticker"]): dict(row) for row in cur.fetchall()}


def _latest_transitions(
    conn: psycopg.Connection,
    parameter_set: str,
    since: dt.date,
) -> dict[str, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (t.ticker)
                t.ticker,
                t.transition_type,
                t.to_bar_date
            FROM hedge_fund.signal_transitions t
            JOIN hedge_fund.scoring_parameters p ON p.id = t.parameter_set_id
            WHERE p.name = %(parameter_set)s
              AND p.is_active = TRUE
              AND t.to_bar_date >= %(since)s
            ORDER BY t.ticker, t.to_bar_date DESC, t.detected_at DESC
            """,
            {"parameter_set": parameter_set, "since": since},
        )
        return {str(row["ticker"]): dict(row) for row in cur.fetchall()}


def _transition_counts(
    conn: psycopg.Connection,
    parameter_set: str,
    since: dt.date,
) -> dict[str, int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.ticker, COUNT(*)::int AS transition_count
            FROM hedge_fund.signal_transitions t
            JOIN hedge_fund.scoring_parameters p ON p.id = t.parameter_set_id
            WHERE p.name = %(parameter_set)s
              AND p.is_active = TRUE
              AND t.to_bar_date >= %(since)s
            GROUP BY t.ticker
            """,
            {"parameter_set": parameter_set, "since": since},
        )
        return {str(row["ticker"]): int(row["transition_count"]) for row in cur.fetchall()}


def _reference_date(conn: psycopg.Connection) -> dt.date:
    with conn.cursor() as cur:
        cur.execute("SELECT max(bar_date) FROM hedge_fund.eod_bars")
        value = cur.fetchone()[0]
    if not value:
        raise RuntimeError("no EOD bar reference date found")
    return value


def _lane_members(
    scores: dict[str, dict[str, Any]],
    transitions: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    lanes = {
        "bullish_alignment": set(),
        "risk_alignment": set(),
        "reentry": set(),
        "mixed_timeframes": set(),
    }
    for ticker, score in scores.items():
        composite = int(score["composite_score"])
        monthly = int(score["monthly_state"])
        weekly = int(score["weekly_state"])
        daily = int(score["daily_state"])
        transition = transitions.get(ticker)
        if composite >= 50:
            lanes["bullish_alignment"].add(ticker)
        if composite <= -50:
            lanes["risk_alignment"].add(ticker)
        if transition and transition["transition_type"] in REENTRY_TRANSITIONS and composite >= 0:
            lanes["reentry"].add(ticker)
        if monthly != weekly or weekly != daily:
            lanes["mixed_timeframes"].add(ticker)
    return lanes


def _lane_deltas(
    production: dict[str, set[str]],
    candidate: dict[str, set[str]],
    *,
    top: int,
) -> list[LaneDelta]:
    rows = []
    for lane in production:
        entered = sorted(candidate[lane] - production[lane])
        exited = sorted(production[lane] - candidate[lane])
        rows.append(
            LaneDelta(
                lane=lane,
                production_count=len(production[lane]),
                candidate_count=len(candidate[lane]),
                entered=entered[:top],
                exited=exited[:top],
            )
        )
    return rows


def _score_deltas(
    production: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    *,
    top: int,
) -> tuple[int, int, list[ScoreDelta]]:
    all_rows = []
    daily_changes = 0
    for ticker in sorted(set(production) & set(candidate)):
        production_score = int(production[ticker]["composite_score"])
        candidate_score = int(candidate[ticker]["composite_score"])
        production_daily = int(production[ticker]["daily_state"])
        candidate_daily = int(candidate[ticker]["daily_state"])
        if production_daily != candidate_daily:
            daily_changes += 1
        delta = candidate_score - production_score
        if delta == 0:
            continue
        all_rows.append(
            ScoreDelta(
                ticker=ticker,
                production_score=production_score,
                candidate_score=candidate_score,
                delta=delta,
                production_daily_state=production_daily,
                candidate_daily_state=candidate_daily,
            )
        )
    all_rows.sort(key=lambda row: (abs(row.delta), row.ticker), reverse=True)
    return len(all_rows), daily_changes, all_rows[:top]


def _whipsaw_rows(
    production_counts: dict[str, int],
    candidate_counts: dict[str, int],
    candidate_latest: dict[str, dict[str, Any]],
    *,
    top: int,
) -> list[WhipsawRow]:
    rows = []
    for ticker in sorted(set(production_counts) | set(candidate_counts)):
        production_count = production_counts.get(ticker, 0)
        candidate_count = candidate_counts.get(ticker, 0)
        delta = candidate_count - production_count
        if candidate_count < 2 and delta <= 0:
            continue
        latest = candidate_latest.get(ticker, {})
        rows.append(
            WhipsawRow(
                ticker=ticker,
                production_transitions=production_count,
                candidate_transitions=candidate_count,
                delta=delta,
                latest_candidate_transition=latest.get("transition_type"),
                latest_candidate_bar_date=latest.get("to_bar_date"),
            )
        )
    rows.sort(key=lambda row: (row.candidate_transitions, row.delta, row.ticker), reverse=True)
    return rows[:top]


def _chart_review_rows(
    conn: psycopg.Connection,
    tickers: list[str],
    *,
    candidate_parameter_set: str,
    sessions: int,
) -> list[ChartReviewRow]:
    rows = []
    for ticker in tickers:
        production_chart = fetch_symbol_chart(conn, ticker=ticker, sessions=sessions)
        candidate_chart = fetch_symbol_chart(
            conn,
            ticker=ticker,
            sessions=sessions,
            parameter_set=candidate_parameter_set,
        )
        production_daily_events = [
            event for event in production_chart["events"] if event["timeframe"] == "daily"
        ]
        candidate_daily_events = [
            event for event in candidate_chart["events"] if event["timeframe"] == "daily"
        ]
        latest = candidate_daily_events[-1] if candidate_daily_events else None
        rows.append(
            ChartReviewRow(
                ticker=ticker,
                production_daily_events=len(production_daily_events),
                candidate_daily_events=len(candidate_daily_events),
                candidate_latest_daily_state=latest["state"] if latest else None,
                candidate_latest_daily_date=latest["bar_date"] if latest else None,
                candidate_latest_trigger_price=latest["trigger_price"] if latest else None,
                candidate_latest_reason=latest["reason"] if latest else None,
            )
        )
    return rows


def _json_default(value: object) -> object:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"{type(value)!r} is not JSON serializable")


def _print_table(rows: list[object], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("(none)")
        return
    widths = []
    rendered_rows = []
    for row in rows:
        raw = asdict(row)
        rendered = [str(raw.get(key) or "-") for key, _ in columns]
        rendered_rows.append(rendered)
    for index, (_, label) in enumerate(columns):
        widths.append(max(len(label), *(len(row[index]) for row in rendered_rows)))
    print(" | ".join(label.ljust(widths[index]) for index, (_, label) in enumerate(columns)))
    print("-|-".join("-" * width for width in widths))
    for rendered in rendered_rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(rendered)))


def main() -> None:
    args = parse_args()
    if args.lookback_days < 1:
        raise SystemExit("lookback-days must be at least 1")
    if args.chart_sessions < 30:
        raise SystemExit("chart-sessions must be at least 30")
    if args.top < 1:
        raise SystemExit("top must be at least 1")

    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        reference_date = _reference_date(conn)
        since = reference_date - dt.timedelta(days=args.lookback_days)
        production_scores = _latest_scores(conn, args.production_parameter_set)
        candidate_scores = _latest_scores(conn, args.candidate_parameter_set)
        production_latest_transitions = _latest_transitions(
            conn, args.production_parameter_set, since
        )
        candidate_latest_transitions = _latest_transitions(
            conn, args.candidate_parameter_set, since
        )
        production_transition_counts = _transition_counts(
            conn, args.production_parameter_set, since
        )
        candidate_transition_counts = _transition_counts(
            conn, args.candidate_parameter_set, since
        )

        lane_deltas = _lane_deltas(
            _lane_members(production_scores, production_latest_transitions),
            _lane_members(candidate_scores, candidate_latest_transitions),
            top=args.top,
        )
        score_delta_count, daily_state_changes, score_deltas = _score_deltas(
            production_scores,
            candidate_scores,
            top=args.top,
        )
        whipsaws = _whipsaw_rows(
            production_transition_counts,
            candidate_transition_counts,
            candidate_latest_transitions,
            top=args.top,
        )
        chart_tickers = []
        for row in score_deltas:
            if row.ticker not in chart_tickers:
                chart_tickers.append(row.ticker)
        for row in whipsaws:
            if row.ticker not in chart_tickers:
                chart_tickers.append(row.ticker)
        charts = _chart_review_rows(
            conn,
            chart_tickers[: args.top],
            candidate_parameter_set=args.candidate_parameter_set,
            sessions=args.chart_sessions,
        )

    payload = {
        "production_parameter_set": args.production_parameter_set,
        "candidate_parameter_set": args.candidate_parameter_set,
        "reference_date": reference_date,
        "since": since,
        "ticker_overlap": len(set(production_scores) & set(candidate_scores)),
        "candidate_tickers": len(candidate_scores),
        "score_delta_count": score_delta_count,
        "daily_state_changes": daily_state_changes,
        "lane_deltas": lane_deltas,
        "score_deltas": score_deltas,
        "whipsaws": whipsaws,
        "chart_reviews": charts,
    }
    if args.json:
        print(json.dumps(payload, default=_json_default, indent=2, sort_keys=True))
        return

    print("Dochia candidate promotion review")
    print(
        f"production={args.production_parameter_set} "
        f"candidate={args.candidate_parameter_set}"
    )
    print(
        f"reference_date={reference_date.isoformat()} since={since.isoformat()} "
        f"candidate_tickers={len(candidate_scores)} overlap={payload['ticker_overlap']}"
    )
    print(
        f"score_delta_count={score_delta_count} "
        f"daily_state_changes={daily_state_changes}"
    )
    print()
    print("Lane deltas")
    _print_table(
        lane_deltas,
        [
            ("lane", "lane"),
            ("production_count", "prod"),
            ("candidate_count", "cand"),
            ("entered", "entered"),
            ("exited", "exited"),
        ],
    )
    print()
    print("Largest score changes")
    _print_table(
        score_deltas,
        [
            ("ticker", "ticker"),
            ("production_score", "prod"),
            ("candidate_score", "cand"),
            ("delta", "delta"),
            ("production_daily_state", "prod daily"),
            ("candidate_daily_state", "cand daily"),
        ],
    )
    print()
    print("Whipsaw clusters")
    _print_table(
        whipsaws,
        [
            ("ticker", "ticker"),
            ("production_transitions", "prod tx"),
            ("candidate_transitions", "cand tx"),
            ("delta", "delta"),
            ("latest_candidate_transition", "latest cand tx"),
            ("latest_candidate_bar_date", "latest date"),
        ],
    )
    print()
    print("Chart-level review")
    _print_table(
        charts,
        [
            ("ticker", "ticker"),
            ("production_daily_events", "prod daily events"),
            ("candidate_daily_events", "cand daily events"),
            ("candidate_latest_daily_state", "latest state"),
            ("candidate_latest_daily_date", "latest date"),
            ("candidate_latest_trigger_price", "trigger"),
            ("candidate_latest_reason", "reason"),
        ],
    )


if __name__ == "__main__":
    main()
