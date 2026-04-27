"""
legal_mail_ingester_cli.py — operator interface for the legal_mail_ingester.

Phase 0a-3 implementation per:
  docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md §6

Subcommands:
  status      — surface per-mailbox ingester state
  pause       — operator-controlled per-mailbox pause (Sub-phase 3B)
  resume      — undo pause (Sub-phase 3B)
  poll        — single-shot dry-run (Sub-phase 3C)
  backfill    — forward-only date-banded recovery (Sub-phase 3D)

Design intent: the operator never has to query email_archive or the state
tables directly. The CLI surfaces health. When something looks off, the
operator runs `fgp legal mail status` and immediately sees which mailbox
is failing, when its last successful patrol was, and what error fired.

This file (Sub-phase 3A) implements:
  - argparse skeleton with subcommands
  - `status` subcommand (read-only)
  - shared helpers (DB connection, output formatting)

Subsequent sub-phases extend the same file:
  3B: pause / resume mutators
  3C: poll --dry-run (IMAP credential validation)
  3D: backfill --since (forward-only recovery)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root + venv are on sys.path so we can import the service
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.services.ediscovery_agent import LegacySession  # noqa: E402
from backend.services.legal_mail_ingester import (  # noqa: E402
    INGESTER_VERSIONED,
    LegalMailboxConfigError,
    load_legal_mailbox_configs,
)


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting helpers
# ─────────────────────────────────────────────────────────────────────────────


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
    """Truncate long strings (last_error) for table display."""
    if not s:
        return ""
    if len(s) <= maxlen:
        return s
    return s[: maxlen - 3] + "..."


# ─────────────────────────────────────────────────────────────────────────────
# `status` subcommand — per-mailbox state surface
# ─────────────────────────────────────────────────────────────────────────────


async def _query_mailbox_state(mailbox_aliases: list[str]) -> list[dict[str, Any]]:
    """
    Build the per-mailbox status row by joining mail_ingester_state +
    mail_ingester_pause + today's counters from event_log.

    For each configured mailbox alias, returns a dict with:
      mailbox, last_patrol_at, last_success_at, last_error,
      paused (bool), pause_reason (optional),
      messages_ingested_today, watchdog_matches_today
    """
    if not mailbox_aliases:
        return []

    today_start_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    out: list[dict[str, Any]] = []
    async with LegacySession() as db:
        # Single round-trip per mailbox (cheap; ≤4 mailboxes typical)
        for alias in mailbox_aliases:
            row: dict[str, Any] = {"mailbox": alias}

            # State row
            r = await db.execute(
                text("""
                    SELECT last_patrol_at, last_success_at, last_error_at, last_error,
                           messages_ingested_total, messages_deduped_total,
                           messages_errored_total, updated_at
                    FROM legal.mail_ingester_state
                    WHERE mailbox_alias = :alias
                """),
                {"alias": alias},
            )
            state = r.fetchone()
            if state is not None:
                row["last_patrol_at"] = state.last_patrol_at
                row["last_success_at"] = state.last_success_at
                row["last_error"] = state.last_error
                row["messages_ingested_total"] = int(state.messages_ingested_total or 0)
                row["messages_errored_total"] = int(state.messages_errored_total or 0)
            else:
                row["last_patrol_at"] = None
                row["last_success_at"] = None
                row["last_error"] = None
                row["messages_ingested_total"] = 0
                row["messages_errored_total"] = 0

            # Pause row
            r = await db.execute(
                text("""
                    SELECT paused_at, paused_by, reason
                    FROM legal.mail_ingester_pause
                    WHERE mailbox_alias = :alias
                """),
                {"alias": alias},
            )
            pause = r.fetchone()
            if pause is not None:
                row["paused"] = True
                row["pause_reason"] = pause.reason or "(no reason given)"
                row["paused_at"] = pause.paused_at
            else:
                row["paused"] = False
                row["pause_reason"] = None
                row["paused_at"] = None

            # Today's counters from event_log (all email.received events emitted by us)
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS events_today,
                        COALESCE(SUM(jsonb_array_length(event_payload->'watchdog_matches')), 0)
                            AS watchdog_matches_today
                    FROM legal.event_log
                    WHERE event_type = 'email.received'
                      AND emitted_by = :v
                      AND emitted_at >= :today_start
                      AND event_payload->>'mailbox' = :alias
                """),
                {
                    "v": INGESTER_VERSIONED,
                    "today_start": today_start_utc,
                    "alias": alias,
                },
            )
            counters = r.fetchone()
            # COUNT(*) always returns exactly one row, so counters is non-None,
            # but Pyright can't infer that from .fetchone() — assert for type narrowing.
            assert counters is not None
            row["messages_ingested_today"] = int(counters.events_today or 0)
            row["watchdog_matches_today"] = int(counters.watchdog_matches_today or 0)

            out.append(row)

    return out


def _print_status_table(rows: list[dict[str, Any]]) -> None:
    """Render the status output as a fixed-column table."""
    if not rows:
        print("(no legal_mail_ingester mailboxes configured — check MAILBOXES_CONFIG)")
        return

    # Header
    print(f"\nlegal_mail_ingester ({INGESTER_VERSIONED}) — per-mailbox status")
    print("=" * 100)
    cols = (
        ("mailbox",          15),
        ("last_patrol",      14),
        ("last_success",     14),
        ("paused",            7),
        ("today_in",          8),
        ("today_wd",          8),
        ("error",            30),
    )
    print(" ".join(f"{name:<{w}}" for name, w in cols))
    print("-" * 100)

    for row in rows:
        paused_str = "PAUSED" if row.get("paused") else "-"
        line = " ".join([
            f"{row['mailbox']:<15}",
            f"{_fmt_age(row.get('last_patrol_at')):<14}",
            f"{_fmt_age(row.get('last_success_at')):<14}",
            f"{paused_str:<7}",
            f"{row.get('messages_ingested_today', 0):<8}",
            f"{row.get('watchdog_matches_today', 0):<8}",
            f"{_truncate(row.get('last_error'), 30):<30}",
        ])
        print(line)
        # Surface pause reason on its own indented line if paused
        if row.get("paused") and row.get("pause_reason"):
            print(f"    └─ pause reason: {row['pause_reason']}")

    print()
    # Operator-friendly summary signals
    paused_count = sum(1 for r in rows if r.get("paused"))
    has_recent_error = any(
        r.get("last_error") for r in rows
    )
    has_stale = any(
        r.get("last_success_at") is None for r in rows
    )
    if paused_count == 0 and not has_recent_error and not has_stale:
        print("All mailboxes healthy.")
    else:
        if paused_count:
            print(f"{paused_count} mailbox(es) paused — use 'fgp legal mail resume' to re-enable")
        if has_recent_error:
            print("Some mailboxes have recent errors — use --json or check legal.mail_ingester_state")
        if has_stale:
            print("Some mailboxes have never had a successful patrol — verify credentials with 'fgp legal mail poll --dry-run'")


# ─────────────────────────────────────────────────────────────────────────────
# Command dispatch
# ─────────────────────────────────────────────────────────────────────────────


async def _cmd_status(args: argparse.Namespace) -> int:
    """Read state + pause + today's counters; render table."""
    try:
        mailboxes = load_legal_mailbox_configs()
    except LegalMailboxConfigError as exc:
        print(f"ERROR: MAILBOXES_CONFIG malformed: {exc}", file=sys.stderr)
        return 2

    aliases = [m.name for m in mailboxes]
    rows = await _query_mailbox_state(aliases)

    # If --mailbox filter provided, narrow rows
    if args.mailbox:
        rows = [r for r in rows if r["mailbox"] == args.mailbox]
        if not rows:
            print(f"ERROR: mailbox {args.mailbox!r} is not configured with ingester=legal_mail",
                  file=sys.stderr)
            return 3

    _print_status_table(rows)
    return 0


# Stubs for 3B/3C/3D — filled in subsequent sub-phases
async def _cmd_pause(_args: argparse.Namespace) -> int:
    print("(pause subcommand — implemented in Sub-phase 3B)", file=sys.stderr)
    return 1


async def _cmd_resume(_args: argparse.Namespace) -> int:
    print("(resume subcommand — implemented in Sub-phase 3B)", file=sys.stderr)
    return 1


async def _cmd_poll(_args: argparse.Namespace) -> int:
    print("(poll subcommand — implemented in Sub-phase 3C)", file=sys.stderr)
    return 1


async def _cmd_backfill(_args: argparse.Namespace) -> int:
    print("(backfill subcommand — implemented in Sub-phase 3D)", file=sys.stderr)
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# argparse setup
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="legal_mail_ingester_cli",
        description=(
            "Operator interface for the legal_mail_ingester. "
            "Read backend/services/legal_mail_ingester.py for service details."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser(
        "status",
        help="Show per-mailbox ingester state",
    )
    p_status.add_argument(
        "--mailbox", default=None,
        help="Narrow output to one mailbox alias (default: all configured)",
    )
    p_status.set_defaults(func=_cmd_status)

    # pause / resume / poll / backfill — stubs in 3A
    p_pause = sub.add_parser("pause", help="(3B) Pause a mailbox")
    p_pause.add_argument("--mailbox", required=True)
    p_pause.add_argument("--reason", default=None)
    p_pause.set_defaults(func=_cmd_pause)

    p_resume = sub.add_parser("resume", help="(3B) Resume a paused mailbox")
    p_resume.add_argument("--mailbox", required=True)
    p_resume.set_defaults(func=_cmd_resume)

    p_poll = sub.add_parser("poll", help="(3C) Single-shot dry-run poll")
    p_poll.add_argument("--mailbox", required=True)
    p_poll.add_argument("--dry-run", action="store_true",
                        help="Required (no live polling supported via CLI)")
    p_poll.set_defaults(func=_cmd_poll)

    p_backfill = sub.add_parser("backfill", help="(3D) Forward-only date-banded recovery")
    p_backfill.add_argument("--mailbox", required=True)
    p_backfill.add_argument("--since", required=True,
                            help="ISO date YYYY-MM-DD; hard floor 2026-03-26 per design v1.1 §6")
    p_backfill.set_defaults(func=_cmd_backfill)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
