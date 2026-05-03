#!/usr/bin/env python3
"""Research v0.3 guardrails for the MarketClub daily range trigger."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.signals.calibration_repository import fetch_daily_sweep_inputs  # noqa: E402
from app.signals.calibration_sweep import (  # noqa: E402
    DailySweepCandidate,
    evaluate_daily_sweep_candidate,
)
from app.signals.guardrail_sweep import (  # noqa: E402
    GuardedRangeCandidate,
    GuardrailSweepResult,
    sweep_guarded_range_candidates,
)
from scripts.sweep_daily_signal_parameters import _database_url  # noqa: E402

DEFAULT_BREAK_PCTS = (Decimal("0"), Decimal("0.001"))
DEFAULT_DEBOUNCE_SESSIONS = (0, 1)
DEFAULT_ATR_PERIODS = (14,)
DEFAULT_ATR_MULTIPLIERS = (
    Decimal("0"),
    Decimal("0.025"),
    Decimal("0.05"),
    Decimal("0.075"),
    Decimal("0.10"),
    Decimal("0.15"),
)
DEFAULT_ADAPTIVE_COOLDOWN_PROFILES = ("off", "20:3:3", "30:4:4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep range-trigger guardrails against MarketClub daily alerts."
    )
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--lookback", action="append", type=int, default=None)
    parser.add_argument("--min-break-pct", action="append", type=Decimal, default=None)
    parser.add_argument("--atr-period", action="append", type=int, default=None)
    parser.add_argument("--atr-multiplier", action="append", type=Decimal, default=None)
    parser.add_argument("--debounce-sessions", action="append", type=int, default=None)
    parser.add_argument(
        "--adaptive-cooldown-profile",
        action="append",
        default=None,
        help="off or lookback:min_events:cooldown_sessions; can be passed more than once.",
    )
    parser.add_argument(
        "--directional-close-mode",
        choices=["both", "none", "required"],
        default="none",
        help="Whether intraday breaks must close in the breakout direction.",
    )
    parser.add_argument("--event-window-days", type=int, default=3)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _break_pct(value: str | Decimal) -> str:
    return f"{Decimal(str(value)) * Decimal('100'):.2f}%"


def _atr_label(period_sessions: int, multiplier: str | Decimal) -> str:
    multiplier_decimal = Decimal(str(multiplier))
    if period_sessions == 0 or multiplier_decimal == 0:
        return "-"
    return f"{period_sessions} x {multiplier_decimal:.3f}"


def _adaptive_label(result: dict[str, Any]) -> str:
    if result["adaptive_cooldown_sessions"] == 0:
        return "-"
    return (
        f"{result['adaptive_cooldown_lookback_sessions']}d/"
        f"{result['adaptive_cooldown_min_events']} -> "
        f"{result['adaptive_cooldown_sessions']}"
    )


def _table_row(values: list[object]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _directional_options(mode: str) -> list[bool]:
    if mode == "none":
        return [False]
    if mode == "required":
        return [True]
    return [False, True]


def _atr_configs(args: argparse.Namespace) -> list[tuple[int, Decimal]]:
    periods = args.atr_period or list(DEFAULT_ATR_PERIODS)
    multipliers = args.atr_multiplier or list(DEFAULT_ATR_MULTIPLIERS)
    configs = {(0, Decimal("0"))}
    for period in periods:
        if period < 1:
            continue
        for multiplier in multipliers:
            if multiplier > 0:
                configs.add((period, multiplier))
    return sorted(configs, key=lambda item: (item[0], item[1]))


def _parse_adaptive_cooldown_profiles(
    profiles: list[str] | None,
) -> list[tuple[int, int, int]]:
    parsed: list[tuple[int, int, int]] = []
    for profile in profiles or list(DEFAULT_ADAPTIVE_COOLDOWN_PROFILES):
        if profile == "off":
            parsed.append((0, 0, 0))
            continue
        try:
            lookback, min_events, sessions = (int(part) for part in profile.split(":"))
        except ValueError as exc:
            raise SystemExit(
                "adaptive-cooldown-profile must be off or lookback:min_events:sessions"
            ) from exc
        parsed.append((lookback, min_events, sessions))
    return parsed


def _candidate_grid(args: argparse.Namespace) -> list[GuardedRangeCandidate]:
    lookbacks = args.lookback or [3]
    min_break_pcts = args.min_break_pct or list(DEFAULT_BREAK_PCTS)
    debounce_sessions = args.debounce_sessions or list(DEFAULT_DEBOUNCE_SESSIONS)
    directional_options = _directional_options(args.directional_close_mode)
    atr_configs = _atr_configs(args)
    adaptive_profiles = _parse_adaptive_cooldown_profiles(args.adaptive_cooldown_profile)
    return [
        GuardedRangeCandidate(
            lookback_sessions=lookback,
            min_break_pct=min_break_pct,
            atr_period_sessions=atr_period,
            atr_multiplier=atr_multiplier,
            debounce_sessions=debounce,
            require_directional_close=require_directional_close,
            adaptive_cooldown_lookback_sessions=adaptive_lookback,
            adaptive_cooldown_min_events=adaptive_min_events,
            adaptive_cooldown_sessions=adaptive_sessions,
        )
        for lookback in lookbacks
        for min_break_pct in min_break_pcts
        for atr_period, atr_multiplier in atr_configs
        for debounce in debounce_sessions
        for require_directional_close in directional_options
        for adaptive_lookback, adaptive_min_events, adaptive_sessions in adaptive_profiles
    ]


def _validate_args(args: argparse.Namespace) -> None:
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit("since cannot be after until")
    if args.top < 1:
        raise SystemExit("top must be at least 1")
    for lookback in args.lookback or [3]:
        if lookback < 1:
            raise SystemExit("lookback must be at least 1")
    for min_break_pct in args.min_break_pct or list(DEFAULT_BREAK_PCTS):
        if min_break_pct < 0 or min_break_pct >= 1:
            raise SystemExit("min-break-pct must be >= 0 and < 1")
    for atr_period in args.atr_period or list(DEFAULT_ATR_PERIODS):
        if atr_period < 1:
            raise SystemExit("atr-period must be at least 1")
    for atr_multiplier in args.atr_multiplier or list(DEFAULT_ATR_MULTIPLIERS):
        if atr_multiplier < 0:
            raise SystemExit("atr-multiplier must be non-negative")
    for debounce in args.debounce_sessions or list(DEFAULT_DEBOUNCE_SESSIONS):
        if debounce < 0:
            raise SystemExit("debounce-sessions must be non-negative")
    for lookback, min_events, sessions in _parse_adaptive_cooldown_profiles(
        args.adaptive_cooldown_profile
    ):
        if (lookback, min_events, sessions) == (0, 0, 0):
            continue
        if lookback < 1 or min_events < 1 or sessions < 1:
            raise SystemExit("adaptive cooldown values must be positive")


def _pick_recommendation(
    results: list[GuardrailSweepResult],
    *,
    raw_range: GuardrailSweepResult,
) -> GuardrailSweepResult | None:
    raw_f1 = raw_range.exact_event_f1 or 0
    minimum_f1 = raw_f1 * 0.85
    eligible = [
        result
        for result in results
        if not (
            result.lookback_sessions == raw_range.lookback_sessions
            and result.min_break_pct == raw_range.min_break_pct
            and result.atr_period_sessions == raw_range.atr_period_sessions
            and result.atr_multiplier == raw_range.atr_multiplier
            and result.debounce_sessions == raw_range.debounce_sessions
            and result.require_directional_close == raw_range.require_directional_close
            and result.adaptive_cooldown_sessions == raw_range.adaptive_cooldown_sessions
            and result.adaptive_cooldown_lookback_sessions
            == raw_range.adaptive_cooldown_lookback_sessions
            and result.adaptive_cooldown_min_events == raw_range.adaptive_cooldown_min_events
        )
        and (result.exact_event_f1 or 0) >= minimum_f1
        and (result.generated_event_reduction or 0) >= 0.15
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda result: (
            result.generated_event_reduction or 0,
            result.exact_event_f1 or 0,
            result.exact_event_precision or 0,
        ),
        reverse=True,
    )
    return eligible[0]


def _render_result_row(result: dict[str, Any], rank: int | str) -> str:
    return _table_row(
        [
            rank,
            result["lookback_sessions"],
            _break_pct(result["min_break_pct"]),
            _atr_label(result["atr_period_sessions"], result["atr_multiplier"]),
            result["debounce_sessions"],
            _adaptive_label(result),
            "yes" if result["require_directional_close"] else "no",
            _pct(result["exact_event_f1"]),
            _pct(result["exact_event_precision"]),
            _pct(result["exact_event_recall"]),
            _pct(result["window_event_recall"]),
            _pct(result["carried_state_accuracy"]),
            result["generated_events"],
            _pct(result["generated_event_reduction"]),
        ]
    )


def _append_results_table(
    lines: list[str],
    *,
    rows: list[dict[str, Any]],
    rank_prefix: str = "",
) -> None:
    lines.extend(
        [
            _table_row(
                [
                    "Rank",
                    "Lookback",
                    "Break buffer",
                    "ATR buffer",
                    "Debounce",
                    "Adaptive cooldown",
                    "Directional close",
                    "F1",
                    "Precision",
                    "Recall",
                    "±3d recall",
                    "Carried",
                    "Generated",
                    "Event reduction",
                ]
            ),
            _table_row(
                [
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---",
                    "---",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                    "---:",
                ]
            ),
        ]
    )
    for rank, result in enumerate(rows, start=1):
        lines.append(_render_result_row(result, f"{rank_prefix}{rank}"))


def _render_markdown(payload: dict[str, Any]) -> str:
    close_baseline = payload["production_close_baseline"]
    raw_range = payload["raw_range_baseline"]
    recommendation = payload["recommendation"]
    lines = [
        "# Dochia v0.3 ATR/Cooldown Guardrail Research",
        "",
        f"Generated: {payload['generated_at']}",
        f"Scope: ticker={payload['ticker'] or 'all'} since={payload['since'] or 'beginning'} until={payload['until'] or 'latest'}",
        f"Event window: ±{payload['event_window_days']} days",
        f"Candidates tested: {payload['candidate_count']}",
        "",
        "## Baselines",
        "",
        _table_row(["Rule", "F1", "Precision", "Recall", "±3d recall", "Carried", "Generated"]),
        _table_row(["---", "---:", "---:", "---:", "---:", "---:", "---:"]),
        _table_row(
            [
                "production close",
                _pct(close_baseline["exact_event_f1"]),
                _pct(close_baseline["exact_event_precision"]),
                _pct(close_baseline["exact_event_recall"]),
                _pct(close_baseline["window_event_recall"]),
                _pct(close_baseline["carried_state_accuracy"]),
                close_baseline["generated_events"],
            ]
        ),
        _table_row(
            [
                "v0.2 raw range",
                _pct(raw_range["exact_event_f1"]),
                _pct(raw_range["exact_event_precision"]),
                _pct(raw_range["exact_event_recall"]),
                _pct(raw_range["window_event_recall"]),
                _pct(raw_range["carried_state_accuracy"]),
                raw_range["generated_events"],
            ]
        ),
        "",
        "## Top Guardrail Candidates",
        "",
    ]
    _append_results_table(lines, rows=payload["top_results"])

    lines.extend(["", "## Best Event-Reduction Candidates", ""])
    _append_results_table(lines, rows=payload["best_reduction_results"], rank_prefix="R")

    lines.extend(["", "## Best Adaptive Cooldown Candidates", ""])
    if payload["best_adaptive_results"]:
        _append_results_table(lines, rows=payload["best_adaptive_results"], rank_prefix="A")
    else:
        lines.append("_No adaptive cooldown candidates were present in this run._")

    lines.extend(["", "## Recommendation", ""])
    if recommendation is None:
        lines.extend(
            [
                "No v0.3 guardrail cleared the default quality bar of at least 85% of raw-range F1 while cutting generated events by at least 15%. Keep v0.2 in candidate-only mode and expand the research grid before promotion.",
                "",
                "Next move: test return-conditioned outcomes and per-ticker whipsaw clusters before persisting another parameter set.",
            ]
        )
    else:
        lines.extend(
            [
                "Use this as the next non-production v0.3 research candidate:",
                "",
                _table_row(
                    [
                        "Lookback",
                        "Break buffer",
                        "ATR buffer",
                        "Debounce",
                        "Adaptive cooldown",
                        "Directional close",
                        "F1",
                        "Precision",
                        "Recall",
                        "Generated",
                        "Event reduction",
                    ]
                ),
                _table_row(
                    ["---:", "---:", "---:", "---:", "---:", "---", "---:", "---:", "---:", "---:", "---:"]
                ),
                _table_row(
                    [
                        recommendation["lookback_sessions"],
                        _break_pct(recommendation["min_break_pct"]),
                        _atr_label(
                            recommendation["atr_period_sessions"],
                            recommendation["atr_multiplier"],
                        ),
                        recommendation["debounce_sessions"],
                        _adaptive_label(recommendation),
                        "yes" if recommendation["require_directional_close"] else "no",
                        _pct(recommendation["exact_event_f1"]),
                        _pct(recommendation["exact_event_precision"]),
                        _pct(recommendation["exact_event_recall"]),
                        recommendation["generated_events"],
                        _pct(recommendation["generated_event_reduction"]),
                    ]
                ),
                "",
                "Decision: keep production on close-break v0 until this v0.3 candidate is persisted as a separate parameter set and reviewed through lane churn, whipsaw pressure, and chart-event deltas.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    candidates = _candidate_grid(args)
    with psycopg.connect(_database_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        observations, bars_by_ticker = fetch_daily_sweep_inputs(
            conn,
            since=args.since,
            until=args.until,
            ticker=args.ticker,
        )

    results = sweep_guarded_range_candidates(
        observations,
        bars_by_ticker,
        candidates=candidates,
        event_window_days=args.event_window_days,
    )
    raw_range = next(
        result
        for result in results
        if result.lookback_sessions == 3
        and result.min_break_pct == Decimal("0")
        and result.atr_period_sessions == 0
        and result.atr_multiplier == Decimal("0")
        and result.debounce_sessions == 0
        and not result.require_directional_close
        and result.adaptive_cooldown_sessions == 0
    )
    close_baseline = evaluate_daily_sweep_candidate(
        observations,
        bars_by_ticker,
        candidate=DailySweepCandidate(lookback_sessions=3, trigger_mode="close"),
        event_window_days=args.event_window_days,
    )
    recommendation = _pick_recommendation(results, raw_range=raw_range)
    top_results = [result.as_json_dict() for result in results[: args.top]]
    best_reduction_results = [
        result.as_json_dict()
        for result in sorted(
            results,
            key=lambda item: (
                item.generated_event_reduction or 0,
                item.exact_event_f1 or 0,
            ),
            reverse=True,
        )[: args.top]
    ]
    best_adaptive_results = [
        result.as_json_dict()
        for result in sorted(
            (
                result
                for result in results
                if result.adaptive_cooldown_sessions > 0
            ),
            key=lambda item: (
                item.exact_event_f1 or 0,
                item.generated_event_reduction or 0,
            ),
            reverse=True,
        )[: args.top]
    ]
    raw_range_payload = raw_range.as_json_dict()
    close_payload = close_baseline.as_json_dict()
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "since": args.since.isoformat() if args.since else None,
        "until": args.until.isoformat() if args.until else None,
        "ticker": args.ticker.upper() if args.ticker else None,
        "event_window_days": args.event_window_days,
        "candidate_count": len(candidates),
        "observation_count": len(observations),
        "production_close_baseline": close_payload,
        "raw_range_baseline": raw_range_payload,
        "top_results": top_results,
        "best_reduction_results": best_reduction_results,
        "best_adaptive_results": best_adaptive_results,
        "recommendation": recommendation.as_json_dict() if recommendation else None,
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
