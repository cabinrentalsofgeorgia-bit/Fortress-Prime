"""Read-only validation report for a daily signal-rule candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.calibration import CalibrationObservation  # noqa: E402
from app.signals.calibration_repository import fetch_daily_sweep_inputs  # noqa: E402
from app.signals.calibration_sweep import (  # noqa: E402
    DailySweepCandidate,
    DailySweepResult,
    evaluate_daily_sweep_candidate,
)
from app.signals.db_preview import normalize_psycopg_url  # noqa: E402
from app.signals.trade_triangles import EodBar  # noqa: E402


@dataclass(frozen=True, slots=True)
class ValidationRow:
    segment: str
    label: str
    since: dt.date | None
    until: dt.date | None
    total_observations: int
    ticker_count: int
    baseline: DailySweepResult
    candidate: DailySweepResult

    @property
    def f1_delta(self) -> float | None:
        return _delta(self.candidate.exact_event_f1, self.baseline.exact_event_f1)

    @property
    def recall_delta(self) -> float | None:
        return _delta(self.candidate.exact_event_recall, self.baseline.exact_event_recall)

    @property
    def precision_delta(self) -> float | None:
        return _delta(self.candidate.exact_event_precision, self.baseline.exact_event_precision)

    def as_json_dict(self) -> dict[str, object]:
        return {
            "segment": self.segment,
            "label": self.label,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "total_observations": self.total_observations,
            "ticker_count": self.ticker_count,
            "baseline": self.baseline.as_json_dict(),
            "candidate": self.candidate.as_json_dict(),
            "f1_delta": self.f1_delta,
            "recall_delta": self.recall_delta,
            "precision_delta": self.precision_delta,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a daily signal-rule candidate against the current baseline."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--baseline-lookback", type=int, default=3)
    parser.add_argument("--baseline-trigger-mode", choices=["close", "range"], default="close")
    parser.add_argument("--candidate-lookback", type=int, default=3)
    parser.add_argument("--candidate-trigger-mode", choices=["close", "range"], default="range")
    parser.add_argument("--event-window-days", type=int, default=3)
    parser.add_argument("--holdout-fraction", type=float, default=0.25)
    parser.add_argument("--top-tickers", type=int, default=15)
    parser.add_argument("--min-slice-observations", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required")
    return normalize_psycopg_url(raw)


def _delta(candidate_value: float | None, baseline_value: float | None) -> float | None:
    if candidate_value is None or baseline_value is None:
        return None
    return candidate_value - baseline_value


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.2f}pt"


def _date_bounds(observations: list[CalibrationObservation]) -> tuple[dt.date | None, dt.date | None]:
    if not observations:
        return None, None
    dates = [observation.trading_day for observation in observations]
    return min(dates), max(dates)


def _quarter_label(trading_day: dt.date) -> str:
    quarter = ((trading_day.month - 1) // 3) + 1
    return f"{trading_day.year}-Q{quarter}"


def _slice_bars(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
) -> dict[str, list[EodBar]]:
    tickers = sorted({observation.ticker for observation in observations})
    return {ticker: bars_by_ticker.get(ticker, []) for ticker in tickers}


def _compare_slice(
    *,
    segment: str,
    label: str,
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    baseline: DailySweepCandidate,
    candidate: DailySweepCandidate,
    event_window_days: int,
) -> ValidationRow:
    since, until = _date_bounds(observations)
    tickers = {observation.ticker for observation in observations}
    bars = _slice_bars(observations, bars_by_ticker)
    baseline_result = evaluate_daily_sweep_candidate(
        observations,
        bars,
        candidate=baseline,
        event_window_days=event_window_days,
    )
    candidate_result = evaluate_daily_sweep_candidate(
        observations,
        bars,
        candidate=candidate,
        event_window_days=event_window_days,
    )
    return ValidationRow(
        segment=segment,
        label=label,
        since=since,
        until=until,
        total_observations=len(observations),
        ticker_count=len(tickers),
        baseline=baseline_result,
        candidate=candidate_result,
    )


def _chronological_rows(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    baseline: DailySweepCandidate,
    candidate: DailySweepCandidate,
    event_window_days: int,
    holdout_fraction: float,
) -> list[ValidationRow]:
    dates = sorted({observation.trading_day for observation in observations})
    if len(dates) < 2:
        return []
    cutoff_index = max(0, min(len(dates) - 2, int(len(dates) * (1 - holdout_fraction)) - 1))
    cutoff = dates[cutoff_index]
    train = [observation for observation in observations if observation.trading_day <= cutoff]
    holdout = [observation for observation in observations if observation.trading_day > cutoff]
    return [
        _compare_slice(
            segment="chronological",
            label=f"train <= {cutoff.isoformat()}",
            observations=train,
            bars_by_ticker=bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=event_window_days,
        ),
        _compare_slice(
            segment="chronological",
            label=f"holdout > {cutoff.isoformat()}",
            observations=holdout,
            bars_by_ticker=bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=event_window_days,
        ),
    ]


def _quarter_rows(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    baseline: DailySweepCandidate,
    candidate: DailySweepCandidate,
    event_window_days: int,
    min_observations: int,
) -> list[ValidationRow]:
    grouped: dict[str, list[CalibrationObservation]] = defaultdict(list)
    for observation in observations:
        grouped[_quarter_label(observation.trading_day)].append(observation)

    rows = []
    for label, group in sorted(grouped.items()):
        if len(group) < min_observations:
            continue
        row = _compare_slice(
            segment="quarter",
            label=label,
            observations=group,
            bars_by_ticker=bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=event_window_days,
        )
        if row.candidate.covered_observations > 0:
            rows.append(row)
    return rows


def _ticker_rows(
    observations: list[CalibrationObservation],
    bars_by_ticker: dict[str, list[EodBar]],
    *,
    baseline: DailySweepCandidate,
    candidate: DailySweepCandidate,
    event_window_days: int,
    top_tickers: int,
    min_observations: int,
) -> list[ValidationRow]:
    counts = Counter(observation.ticker for observation in observations)
    rows = []
    for ticker, count in counts.most_common():
        if len(rows) >= top_tickers:
            break
        if count < min_observations:
            continue
        group = [observation for observation in observations if observation.ticker == ticker]
        row = _compare_slice(
            segment="ticker",
            label=ticker,
            observations=group,
            bars_by_ticker=bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=event_window_days,
        )
        if row.candidate.covered_observations > 0:
            rows.append(row)
    return rows


def _print_rows(title: str, rows: list[ValidationRow]) -> None:
    print(title)
    print(
        "label                    | obs   | covered | tickers | base f1 | cand f1 | "
        "delta   | cand recall | cand precision | cand carried"
    )
    print(
        "-------------------------|-------|---------|---------|---------|---------|"
        "---------|-------------|----------------|-------------"
    )
    for row in rows:
        print(
            f"{row.label[:24]:<24} | "
            f"{row.total_observations:>5} | "
            f"{row.candidate.covered_observations:>7} | "
            f"{row.ticker_count:>7} | "
            f"{_pct(row.baseline.exact_event_f1):>7} | "
            f"{_pct(row.candidate.exact_event_f1):>7} | "
            f"{_signed_pct(row.f1_delta):>7} | "
            f"{_pct(row.candidate.exact_event_recall):>11} | "
            f"{_pct(row.candidate.exact_event_precision):>14} | "
            f"{_pct(row.candidate.carried_state_accuracy):>11}"
        )
    print()


def _print_report(rows: list[ValidationRow], *, baseline: DailySweepCandidate, candidate: DailySweepCandidate) -> None:
    print("Daily MarketClub candidate validation")
    print(
        f"baseline={baseline.lookback_sessions}/{baseline.trigger_mode} "
        f"candidate={candidate.lookback_sessions}/{candidate.trigger_mode}"
    )
    print()
    for segment in ("overall", "chronological", "quarter", "ticker"):
        segment_rows = [row for row in rows if row.segment == segment]
        if segment_rows:
            _print_rows(segment.capitalize(), segment_rows)


def main() -> None:
    args = parse_args()
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit("since cannot be after until")
    if not 0 < args.holdout_fraction < 1:
        raise SystemExit("holdout-fraction must be between 0 and 1")
    if args.min_slice_observations < 1:
        raise SystemExit("min-slice-observations must be at least 1")
    if args.top_tickers < 1:
        raise SystemExit("top-tickers must be at least 1")

    baseline = DailySweepCandidate(
        lookback_sessions=args.baseline_lookback,
        trigger_mode=args.baseline_trigger_mode,
    )
    candidate = DailySweepCandidate(
        lookback_sessions=args.candidate_lookback,
        trigger_mode=args.candidate_trigger_mode,
    )

    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        observations, bars_by_ticker = fetch_daily_sweep_inputs(
            conn,
            since=args.since,
            until=args.until,
            ticker=args.ticker,
        )

    rows = [
        _compare_slice(
            segment="overall",
            label="all",
            observations=observations,
            bars_by_ticker=bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=args.event_window_days,
        )
    ]
    rows.extend(
        _chronological_rows(
            observations,
            bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=args.event_window_days,
            holdout_fraction=args.holdout_fraction,
        )
    )
    rows.extend(
        _quarter_rows(
            observations,
            bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=args.event_window_days,
            min_observations=args.min_slice_observations,
        )
    )
    rows.extend(
        _ticker_rows(
            observations,
            bars_by_ticker,
            baseline=baseline,
            candidate=candidate,
            event_window_days=args.event_window_days,
            top_tickers=args.top_tickers,
            min_observations=args.min_slice_observations,
        )
    )

    if args.json:
        print(json.dumps([row.as_json_dict() for row in rows], indent=2, sort_keys=True))
    else:
        _print_report(rows, baseline=baseline, candidate=candidate)


if __name__ == "__main__":
    main()
