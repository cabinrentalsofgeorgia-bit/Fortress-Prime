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

Implemented sub-phases:
  3A: argparse skeleton + `status` subcommand (read-only)
  3B: pause / resume mutators (bilateral write to legal.mail_ingester_pause)
  3C: poll --dry-run (IMAP credential validation; no DB writes)

Pending sub-phases:
  3D: backfill --since (forward-only recovery)
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
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
    LegalMailIngesterTransport,
    ProdSession,
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


# ─────────────────────────────────────────────────────────────────────────────
# Mutator helpers (3B)
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_operator() -> str:
    """
    Resolve the operator identity for the audit trail in mail_ingester_pause.

    Resolution order:
      1. FLOS_OPERATOR env var (explicit override for ops scripts)
      2. SUDO_USER (when invoked under sudo)
      3. USER / LOGNAME / getpass.getuser() (the underlying caller)

    The pause table requires paused_by NOT NULL — so we always return a
    non-empty string. Defaults to 'unknown' rather than raising; CLI must
    never fail because of a missing env var, the audit row is more useful
    than a hard failure.
    """
    for var in ("FLOS_OPERATOR", "SUDO_USER", "USER", "LOGNAME"):
        v = os.environ.get(var)
        if v:
            return v
    try:
        return getpass.getuser() or "unknown"
    except Exception:
        return "unknown"


def _validate_mailbox_alias(alias: str) -> Optional[str]:
    """
    Confirm `alias` is one of the configured legal mailboxes.

    Returns the canonical alias on match, or None if no match.
    Returning None lets the caller print a helpful error listing valid
    aliases instead of silently writing pause rows for nonsense names.
    """
    try:
        configs = load_legal_mailbox_configs()
    except LegalMailboxConfigError:
        return None
    for cfg in configs:
        if cfg.name == alias:
            return cfg.name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# `pause` and `resume` subcommands (3B)
# ─────────────────────────────────────────────────────────────────────────────


async def _cmd_pause(args: argparse.Namespace) -> int:
    """
    Insert (or refresh) a row in legal.mail_ingester_pause for the given
    mailbox. The patrol loop checks this table every cycle via
    _is_mailbox_paused() and skips the mailbox while a row exists.

    Bilateral: legacy then prod. Prod failure is logged but doesn't fail
    the command — pause is a control-plane signal and the patrol loop
    reads from fortress_db (legacy) anyway. The mirror exists so the prod
    side has the audit trail.
    """
    alias = _validate_mailbox_alias(args.mailbox)
    if alias is None:
        print(
            f"ERROR: mailbox {args.mailbox!r} is not configured with ingester=legal_mail",
            file=sys.stderr,
        )
        try:
            valid = [c.name for c in load_legal_mailbox_configs()]
            if valid:
                print(f"  configured aliases: {', '.join(valid)}", file=sys.stderr)
        except LegalMailboxConfigError:
            pass
        return 3

    operator = _resolve_operator()
    reason = args.reason or f"operator pause via CLI by {operator}"

    upsert_sql = text("""
        INSERT INTO legal.mail_ingester_pause
            (mailbox_alias, paused_by, reason, paused_at)
        VALUES
            (:alias, :operator, :reason, NOW())
        ON CONFLICT (mailbox_alias) DO UPDATE
        SET paused_by = EXCLUDED.paused_by,
            reason    = EXCLUDED.reason,
            paused_at = EXCLUDED.paused_at
        RETURNING paused_at
    """)
    params = {"alias": alias, "operator": operator, "reason": reason}

    # Legacy (canonical) write
    async with LegacySession() as db:
        r = await db.execute(upsert_sql, params)
        row = r.fetchone()
        await db.commit()
    paused_at = row.paused_at if row is not None else None

    # Prod mirror — log-but-don't-fail
    prod_mirrored = True
    try:
        async with ProdSession() as prod:
            await prod.execute(upsert_sql, params)
            await prod.commit()
    except Exception as exc:
        prod_mirrored = False
        print(
            f"WARNING: legacy write succeeded but fortress_prod mirror failed: {exc}",
            file=sys.stderr,
        )

    print(f"PAUSED mailbox={alias!r}")
    print(f"  by:     {operator}")
    print(f"  reason: {reason}")
    if paused_at is not None:
        print(f"  at:     {_fmt_age(paused_at)}")
    if not prod_mirrored:
        print("  mirror: legacy=ok prod=FAILED (re-run pause to retry mirror)")
    print()
    print(f"Patrol loop will skip {alias!r} on its next cycle.")
    print(f"To resume: fgp legal mail resume --mailbox {alias}")
    return 0


async def _cmd_resume(args: argparse.Namespace) -> int:
    """
    Delete the pause row for the given mailbox. If no row exists, this is
    a no-op and returns 0 (idempotent — operator may run resume defensively).

    Bilateral: legacy then prod. Prod failure logged but doesn't fail.
    """
    alias = _validate_mailbox_alias(args.mailbox)
    if alias is None:
        print(
            f"ERROR: mailbox {args.mailbox!r} is not configured with ingester=legal_mail",
            file=sys.stderr,
        )
        return 3

    delete_sql = text("""
        DELETE FROM legal.mail_ingester_pause
        WHERE mailbox_alias = :alias
        RETURNING paused_at, paused_by, reason
    """)
    params = {"alias": alias}

    async with LegacySession() as db:
        r = await db.execute(delete_sql, params)
        deleted = r.fetchone()
        await db.commit()

    prod_mirrored = True
    try:
        async with ProdSession() as prod:
            await prod.execute(delete_sql, params)
            await prod.commit()
    except Exception as exc:
        prod_mirrored = False
        print(
            f"WARNING: legacy delete succeeded but fortress_prod mirror failed: {exc}",
            file=sys.stderr,
        )

    if deleted is None:
        print(f"NOOP — mailbox {alias!r} was not paused. Nothing to resume.")
    else:
        print(f"RESUMED mailbox={alias!r}")
        print(f"  was paused by:     {deleted.paused_by}")
        print(f"  was paused reason: {deleted.reason}")
        print(f"  was paused since:  {_fmt_age(deleted.paused_at)}")
        if not prod_mirrored:
            print("  mirror: legacy=ok prod=FAILED (re-run resume to retry mirror)")
        print()
        print(f"Patrol loop will resume polling {alias!r} on its next cycle.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# `poll --dry-run` subcommand (3C)
# ─────────────────────────────────────────────────────────────────────────────


async def _cmd_poll(args: argparse.Namespace) -> int:
    """
    Read-only IMAP credential + connectivity probe for one mailbox.

    Required gate before flipping LEGAL_MAIL_INGESTER_ENABLED=true. The
    probe connects, runs the same banded SEARCH the patrol uses, and
    surfaces UID count + a header-only preview of the most recent
    messages in the band — without touching email_archive, event_log,
    or the \\Seen flag.

    --dry-run is required (no live polling supported via CLI). The flag
    is enforced rather than implicit so accidental invocation can never
    write to email_archive.
    """
    if not args.dry_run:
        print(
            "ERROR: --dry-run is required. CLI does not support live polling — "
            "the patrol loop in worker.py is the only path that writes.",
            file=sys.stderr,
        )
        return 4

    alias = _validate_mailbox_alias(args.mailbox)
    if alias is None:
        print(
            f"ERROR: mailbox {args.mailbox!r} is not configured with ingester=legal_mail",
            file=sys.stderr,
        )
        return 3

    try:
        configs = load_legal_mailbox_configs()
    except LegalMailboxConfigError as exc:
        print(f"ERROR: MAILBOXES_CONFIG malformed: {exc}", file=sys.stderr)
        return 2

    cfg = next((c for c in configs if c.name == alias), None)
    if cfg is None:
        print(f"ERROR: mailbox {alias!r} resolved but config missing (race?)",
              file=sys.stderr)
        return 3

    if cfg.transport != "imap":
        print(
            f"ERROR: mailbox {alias!r} transport={cfg.transport!r}; "
            "only imap probes are supported",
            file=sys.stderr,
        )
        return 5

    print(f"\nDry-run probe — mailbox={alias!r} ({INGESTER_VERSIONED})")
    print(f"  host:     {cfg.host}:{cfg.port}")
    print(f"  folder:   {cfg.folder}")
    print(f"  band:     UNSEEN SINCE today - {cfg.search_band_days} days")
    print(f"  max/poll: {cfg.max_messages_per_patrol}")
    print()
    print("Connecting…")

    try:
        transport = LegalMailIngesterTransport(cfg)
    except (ValueError, LegalMailboxConfigError) as exc:
        print(f"ERROR: transport setup failed: {exc}", file=sys.stderr)
        return 6

    # imaplib is sync; offload to a thread so we don't block the event loop.
    # Probe path is short-lived (one connect / one SEARCH / N header fetches).
    try:
        result = await asyncio.to_thread(transport.probe, args.limit)
    except LegalMailboxConfigError as exc:
        # Specific signal — credentials_ref unset / empty
        print(f"ERROR: credential resolution failed: {exc}", file=sys.stderr)
        print("  Check the credentials_ref entry in MAILBOXES_CONFIG and the matching .env var.",
              file=sys.stderr)
        return 7
    except Exception as exc:
        # Generic IMAP error — login failure, host unreachable, TLS rejection, etc.
        # Surface cleanly so the operator sees the actual server response.
        print(f"ERROR: probe failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 8

    print(f"  ✓ login OK")
    print(f"  ✓ folder selected (readonly)")
    print(f"  ✓ SEARCH executed: {result['search_predicate']}")
    print()
    print(f"UIDs in band (UNSEEN since {result['since_date']}): {result['uids_in_band']}")

    previews = result.get("recent_subjects") or []
    if previews:
        print()
        print(f"Most recent {len(previews)} subject(s) (header-only fetch — \\Seen NOT mutated):")
        print("-" * 100)
        for p in previews:
            print(f"  uid {p['uid']:>8}  {p['date_header'][:32]:<32}  {p['sender'][:30]:<30}")
            print(f"             └─ {p['subject']}")
        print("-" * 100)
    else:
        print()
        print("(no messages currently in band — band is empty or all already \\Seen)")

    print()
    print("Probe complete. NO writes to email_archive, event_log, or any DB.")
    print("\\Seen flag NOT mutated — Captain coexistence preserved.")
    return 0


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

    # pause: write legal.mail_ingester_pause row (bilateral)
    p_pause = sub.add_parser(
        "pause",
        help="Pause a mailbox — patrol loop will skip it next cycle",
    )
    p_pause.add_argument("--mailbox", required=True,
                         help="Mailbox alias (must be configured in MAILBOXES_CONFIG)")
    p_pause.add_argument("--reason", default=None,
                         help="Why this mailbox is being paused (recorded in audit trail)")
    p_pause.set_defaults(func=_cmd_pause)

    # resume: delete legal.mail_ingester_pause row (bilateral)
    p_resume = sub.add_parser(
        "resume",
        help="Resume a paused mailbox — patrol loop polls it next cycle",
    )
    p_resume.add_argument("--mailbox", required=True,
                          help="Mailbox alias (idempotent if not currently paused)")
    p_resume.set_defaults(func=_cmd_resume)

    # poll: read-only IMAP probe (--dry-run required — no live polling via CLI)
    p_poll = sub.add_parser(
        "poll",
        help="Dry-run IMAP probe — connects, runs banded SEARCH, surfaces preview (no DB writes)",
    )
    p_poll.add_argument("--mailbox", required=True,
                        help="Mailbox alias to probe")
    p_poll.add_argument("--dry-run", action="store_true",
                        help="Required — CLI never performs live polling")
    p_poll.add_argument("--limit", type=int, default=5,
                        help="Number of recent subjects to preview (default: 5; header-only fetch)")
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
