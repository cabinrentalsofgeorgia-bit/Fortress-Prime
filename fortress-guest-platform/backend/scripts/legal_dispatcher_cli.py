"""
legal_dispatcher_cli.py — operator interface for the legal_dispatcher.

Phase 1-4 implementation per:
  docs/architecture/cross-division/FLOS-phase-1-4-cli-health-implementation.md

Subcommands (mirrors PR #247 legal_mail_ingester_cli.py conventions
verbatim — argparse, async-internal via asyncio.run, direct DB access
via LegacySession + ProdSession, no JWT — operator script):

  dispatcher status                                — surface dispatcher state
  dispatcher pause [--reason "..."]                — bilateral pause (1-4B)
  dispatcher resume                                — bilateral resume  (1-4B)
  dispatcher replay --event-id N [--confirm]       — clear processed_at (1-4C)
  dispatcher dead-letter list [--limit 50]         — read DLQ          (1-4D)
  dispatcher dead-letter purge --before YYYY-MM-DD --confirm
                                                   — bilateral DLQ purge (1-4D)
  posture get --case-slug X [--json]               — read case_posture (1-4D)
  posture history --case-slug X [--limit 20]       — walk event_log    (1-4D)

This file (Sub-phase 1-4A) implements:
  - argparse skeleton with all 8 subcommands declared (nested
    `dispatcher`/`posture` topic groups; `dead-letter` further nested
    under `dispatcher`)
  - `dispatcher status` subcommand (read-only)
  - shared helpers (DB connection, output formatting)

Subsequent sub-phases extend the same file:
  1-4B: pause / resume mutators (bilateral writes to dispatcher_pause)
  1-4C: replay (plan-by-default + dead-letter-emitted refusal guard)
  1-4D: posture get / posture history / dead-letter list / dead-letter purge
  1-4E: companion file backend/api/legal_dispatcher_health.py + main.py
        registration (no edits to this file)

Validation gate before Phase 1-5 cutover: operator runs
`legal_dispatcher_cli.py dispatcher status` to verify routes loaded +
queue empty before flipping LEGAL_DISPATCHER_ENABLED=true.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root is on sys.path so we can import backend.* modules
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.services.ediscovery_agent import LegacySession  # noqa: E402
from backend.services.legal_dispatcher import (  # noqa: E402
    BATCH_SIZE,
    DISPATCHER_VERSIONED,
    POLL_INTERVAL_SEC,
)


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting helpers (inline-pasted from PR #247 per established
# Phase 0a-3 precedent — kept per-CLI rather than shared-imported)
# ─────────────────────────────────────────────────────────────────────────────


def _fmt_ts(ts: Optional[datetime]) -> str:
    """Format a TIMESTAMPTZ for table display. None → '(never)'."""
    if ts is None:
        return "(never)"
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_age(ts: Optional[datetime]) -> str:
    """Time elapsed since `ts` in human-readable form. None → '(never)'."""
    if ts is None:
        return "(never)"
    delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _truncate(s: Optional[str], maxlen: int = 60) -> str:
    """Truncate long strings (last_error etc.) for table display."""
    if not s:
        return ""
    if len(s) <= maxlen:
        return s
    return s[: maxlen - 3] + "..."


# ─────────────────────────────────────────────────────────────────────────────
# `dispatcher status` subcommand (1-4A — read-only)
#
# Reads four data sources and emits a human-readable report:
#   1. legal.dispatcher_routes      — event_type → handler map
#   2. legal.dispatcher_pause       — singleton pause state
#   3. legal.event_log              — queue depth + oldest unprocessed age
#   4. legal.dispatcher_event_attempts — last-hour aggregates
# ─────────────────────────────────────────────────────────────────────────────


async def _query_routes() -> list[dict[str, Any]]:
    """Read dispatcher_routes ordered by event_type."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT event_type, handler_module, handler_function, enabled, max_retries
            FROM legal.dispatcher_routes
            ORDER BY event_type
        """))
        return [dict(r._mapping) for r in result.fetchall()]


async def _query_pause() -> Optional[dict[str, Any]]:
    """Read dispatcher_pause singleton row. None if not paused."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT paused_at, paused_by, reason
            FROM legal.dispatcher_pause
            WHERE singleton_id = 1
            LIMIT 1
        """))
        row = result.fetchone()
        return dict(row._mapping) if row is not None else None


async def _query_queue() -> dict[str, Any]:
    """Read queue depth + oldest unprocessed age in one query."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT
                COUNT(*) AS unprocessed_total,
                EXTRACT(EPOCH FROM (NOW() - MIN(emitted_at))) AS oldest_unprocessed_age_sec
            FROM legal.event_log
            WHERE processed_at IS NULL
        """))
        row = result.fetchone()
        if row is None:
            return {"unprocessed_total": 0, "oldest_unprocessed_age_sec": None}
        age_sec = row.oldest_unprocessed_age_sec
        return {
            "unprocessed_total": int(row.unprocessed_total or 0),
            "oldest_unprocessed_age_sec": float(age_sec) if age_sec is not None else None,
        }


async def _query_last_hour_aggregates() -> dict[str, Any]:
    """Read last-hour aggregates from dispatcher_event_attempts."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT
                SUM(CASE WHEN outcome = 'success'     THEN 1 ELSE 0 END) AS processed_last_hour,
                SUM(CASE WHEN outcome = 'error'       THEN 1 ELSE 0 END) AS failed_last_hour,
                SUM(CASE WHEN outcome = 'dead_letter' THEN 1 ELSE 0 END) AS dead_lettered_last_hour,
                AVG(duration_ms)                                          AS mean_handler_ms,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_handler_ms
            FROM legal.dispatcher_event_attempts
            WHERE attempted_at >= NOW() - INTERVAL '1 hour'
        """))
        row = result.fetchone()
        if row is None:
            return {
                "processed_last_hour": 0,
                "failed_last_hour": 0,
                "dead_lettered_last_hour": 0,
                "mean_handler_ms": None,
                "p99_handler_ms": None,
            }
        return {
            "processed_last_hour": int(row.processed_last_hour or 0),
            "failed_last_hour": int(row.failed_last_hour or 0),
            "dead_lettered_last_hour": int(row.dead_lettered_last_hour or 0),
            "mean_handler_ms": float(row.mean_handler_ms) if row.mean_handler_ms is not None else None,
            "p99_handler_ms": float(row.p99_handler_ms) if row.p99_handler_ms is not None else None,
        }


def _print_status(
    routes: list[dict[str, Any]],
    pause: Optional[dict[str, Any]],
    queue: dict[str, Any],
    aggregates: dict[str, Any],
    flag_enabled: bool,
) -> None:
    """Render the operator-readable status report."""
    enabled_count = sum(1 for r in routes if r["enabled"])
    placeholder_count = len(routes) - enabled_count

    # Compute overall_status (matches health endpoint semantics — Phase 1-4E)
    if not flag_enabled:
        overall = "disabled"
    elif aggregates["failed_last_hour"] > 0 or aggregates["dead_lettered_last_hour"] > 0:
        overall = "degraded"
    elif (
        queue["oldest_unprocessed_age_sec"] is not None
        and queue["oldest_unprocessed_age_sec"] > 60.0  # LAG_THRESHOLD_SEC LOCKED
    ):
        overall = "lagging"
    else:
        overall = "ok"

    print(f"\nlegal_dispatcher ({DISPATCHER_VERSIONED}) — operator status")
    print("=" * 100)
    print(f"flag enabled:         {str(flag_enabled).lower()}")
    print(f"overall:              {overall}")
    print(f"poll cadence:         every {POLL_INTERVAL_SEC}s; batch size {BATCH_SIZE}")
    print()

    # ── Routes table ────────────────────────────────────────────────────
    print(f"routes ({len(routes)} total, {enabled_count} live, {placeholder_count} placeholder)")
    print(f"  {'event_type':<32} {'handler':<48} {'enabled':<8} {'max_retries'}")
    for r in routes:
        handler_disp = _truncate(r["handler_function"], 47)
        print(
            f"  {r['event_type']:<32} {handler_disp:<48} "
            f"{str(r['enabled']).lower():<8} {r['max_retries']}"
        )
    print()

    # ── Queue ───────────────────────────────────────────────────────────
    print("queue")
    print(f"  unprocessed_total:    {queue['unprocessed_total']}")
    if queue["oldest_unprocessed_age_sec"] is None:
        print(f"  oldest_unprocessed:   (none)")
    else:
        age_sec = queue["oldest_unprocessed_age_sec"]
        print(f"  oldest_unprocessed:   {age_sec:.1f}s ago")
    print()

    # ── Last-hour aggregates ────────────────────────────────────────────
    print("last hour (from dispatcher_event_attempts)")
    print(f"  processed:            {aggregates['processed_last_hour']}")
    print(f"  failed:               {aggregates['failed_last_hour']}")
    print(f"  dead_lettered:        {aggregates['dead_lettered_last_hour']}")
    if aggregates["mean_handler_ms"] is not None:
        print(f"  mean_handler_ms:      {aggregates['mean_handler_ms']:.1f}")
    else:
        print(f"  mean_handler_ms:      —")
    if aggregates["p99_handler_ms"] is not None:
        print(f"  p99_handler_ms:       {aggregates['p99_handler_ms']:.1f}")
    else:
        print(f"  p99_handler_ms:       —")
    print()

    # ── Pause state ─────────────────────────────────────────────────────
    print("pause")
    if pause is None:
        print("  not paused")
    else:
        print(f"  paused_at:            {_fmt_ts(pause['paused_at'])} ({_fmt_age(pause['paused_at'])})")
        print(f"  paused_by:            {pause['paused_by']}")
        print(f"  reason:               {pause.get('reason') or '(no reason given)'}")
    print()

    # ── Operator-friendly summary signals ───────────────────────────────
    if not flag_enabled:
        print("dispatcher disabled at boot; CLI mutators still work; flip "
              "LEGAL_DISPATCHER_ENABLED=true to start the loop")
    elif pause is not None:
        print("DISPATCHER PAUSED — see paused_by / reason; resume with "
              "`legal_dispatcher_cli dispatcher resume`")
    elif overall == "lagging":
        print(f"queue lag — oldest unprocessed event is "
              f"{queue['oldest_unprocessed_age_sec']:.1f}s old; "
              f"investigate handler latency or pause/replay if needed")
    elif overall == "degraded":
        print(f"failed/dead-lettered events in last hour — check "
              f"`legal_dispatcher_cli dispatcher dead-letter list` and recent attempts")
    else:
        print("all routes loaded; queue healthy; dispatcher running normally")


async def _cmd_dispatcher_status(_args: argparse.Namespace) -> int:
    """Read state from 4 sources; render report."""
    # Imports placed inside the function so they don't fire on argparse-only
    # invocations (--help). Same idiom as PR #247.
    from backend.core.config import settings

    routes = await _query_routes()
    pause = await _query_pause()
    queue = await _query_queue()
    aggregates = await _query_last_hour_aggregates()

    _print_status(
        routes=routes,
        pause=pause,
        queue=queue,
        aggregates=aggregates,
        flag_enabled=bool(settings.legal_dispatcher_enabled),
    )
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Stub command handlers for sub-phases 1-4B / 1-4C / 1-4D
# ─────────────────────────────────────────────────────────────────────────────


async def _cmd_dispatcher_pause(_args: argparse.Namespace) -> int:
    print("(dispatcher pause — implemented in Sub-phase 1-4B)", file=sys.stderr)
    return 1


async def _cmd_dispatcher_resume(_args: argparse.Namespace) -> int:
    print("(dispatcher resume — implemented in Sub-phase 1-4B)", file=sys.stderr)
    return 1


async def _cmd_dispatcher_replay(_args: argparse.Namespace) -> int:
    print("(dispatcher replay — implemented in Sub-phase 1-4C)", file=sys.stderr)
    return 1


async def _cmd_dispatcher_dead_letter_list(_args: argparse.Namespace) -> int:
    print("(dispatcher dead-letter list — implemented in Sub-phase 1-4D)", file=sys.stderr)
    return 1


async def _cmd_dispatcher_dead_letter_purge(_args: argparse.Namespace) -> int:
    print("(dispatcher dead-letter purge — implemented in Sub-phase 1-4D)", file=sys.stderr)
    return 1


async def _cmd_posture_get(_args: argparse.Namespace) -> int:
    print("(posture get — implemented in Sub-phase 1-4D)", file=sys.stderr)
    return 1


async def _cmd_posture_history(_args: argparse.Namespace) -> int:
    print("(posture history — implemented in Sub-phase 1-4D)", file=sys.stderr)
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# argparse setup — three-level nesting:
#   top → topic (dispatcher | posture) → subcommand (and dead-letter further
#   sub-subparses to list | purge)
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="legal_dispatcher_cli",
        description=(
            "Operator interface for the legal_dispatcher. "
            "Read backend/services/legal_dispatcher.py for service details."
        ),
    )
    topic_subs = p.add_subparsers(dest="topic", required=True)

    # ── topic: dispatcher ───────────────────────────────────────────────
    p_dispatcher = topic_subs.add_parser(
        "dispatcher",
        help="dispatcher control: status, pause, resume, replay, dead-letter ops",
    )
    cmd_subs = p_dispatcher.add_subparsers(dest="command", required=True)

    p_status = cmd_subs.add_parser(
        "status", help="Show dispatcher state (routes, queue, last-hour metrics)"
    )
    p_status.set_defaults(func=_cmd_dispatcher_status)

    p_pause = cmd_subs.add_parser(
        "pause", help="(1-4B) Pause the dispatcher — bilateral write to dispatcher_pause"
    )
    p_pause.add_argument(
        "--reason", default=None,
        help="Why the dispatcher is being paused (recorded in audit trail)",
    )
    p_pause.set_defaults(func=_cmd_dispatcher_pause)

    p_resume = cmd_subs.add_parser(
        "resume", help="(1-4B) Resume the dispatcher — bilateral delete from dispatcher_pause"
    )
    p_resume.set_defaults(func=_cmd_dispatcher_resume)

    p_replay = cmd_subs.add_parser(
        "replay", help="(1-4C) Replay one event — plan-by-default; --confirm to execute"
    )
    p_replay.add_argument("--event-id", type=int, required=True,
                          help="legal.event_log.id of the event to replay")
    p_replay.add_argument("--confirm", action="store_true",
                          help="Required to execute; without it, plan only")
    p_replay.set_defaults(func=_cmd_dispatcher_replay)

    # dispatcher dead-letter (sub-subparser)
    p_dlq = cmd_subs.add_parser(
        "dead-letter",
        help="(1-4D) Dead-letter queue ops: list, purge",
    )
    dlq_subs = p_dlq.add_subparsers(dest="dlq_command", required=True)

    p_dlq_list = dlq_subs.add_parser(
        "list", help="(1-4D) List dispatcher_dead_letter rows ordered by dead_lettered_at DESC"
    )
    p_dlq_list.add_argument("--limit", type=int, default=50,
                            help="Maximum rows to display (default: 50)")
    p_dlq_list.set_defaults(func=_cmd_dispatcher_dead_letter_list)

    p_dlq_purge = dlq_subs.add_parser(
        "purge",
        help="(1-4D) Operator-triggered DLQ purge — plan-by-default; --confirm to execute",
    )
    p_dlq_purge.add_argument("--before", required=True,
                             help="ISO date YYYY-MM-DD; rows older than this date deleted")
    p_dlq_purge.add_argument("--confirm", action="store_true",
                             help="Required to execute; without it, plan only")
    p_dlq_purge.set_defaults(func=_cmd_dispatcher_dead_letter_purge)

    # ── topic: posture ──────────────────────────────────────────────────
    p_posture = topic_subs.add_parser(
        "posture",
        help="case_posture inspection: get, history",
    )
    posture_subs = p_posture.add_subparsers(dest="command", required=True)

    p_posture_get = posture_subs.add_parser(
        "get", help="(1-4D) Read case_posture row for one case"
    )
    p_posture_get.add_argument("--case-slug", required=True,
                               help="legal.case_posture.case_slug to surface")
    p_posture_get.add_argument("--json", action="store_true",
                               help="Emit full row as JSON for tooling")
    p_posture_get.set_defaults(func=_cmd_posture_get)

    p_posture_history = posture_subs.add_parser(
        "history", help="(1-4D) Walk legal.event_log for one case in time order"
    )
    p_posture_history.add_argument("--case-slug", required=True,
                                   help="legal.event_log.case_slug to filter on")
    p_posture_history.add_argument("--limit", type=int, default=20,
                                   help="Maximum events to display (default: 20)")
    p_posture_history.set_defaults(func=_cmd_posture_history)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
