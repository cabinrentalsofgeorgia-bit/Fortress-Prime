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
  3D: backfill --since YYYY-MM-DD (forward-only; hard floor 2026-03-26)
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root + venv are on sys.path so we can import the service
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.services.ediscovery_agent import LegacySession  # noqa: E402
from backend.services.legal_mail_ingester import (  # noqa: E402
    BACKFILL_HARD_FLOOR,
    INGESTER_VERSIONED,
    LegalMailboxConfigError,
    LegalMailIngesterTransport,
    ProdSession,
    classify_inbound,
    emit_email_received_event,
    load_legal_mailbox_configs,
    parse_message,
    write_email_archive_bilateral,
)
from backend.services.legal_mail_ingester import (  # noqa: E402
    _is_mailbox_paused,
    _load_priority_sender_rules,
    _load_watchdog_rules,
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


# ─────────────────────────────────────────────────────────────────────────────
# `backfill --mailbox X --since YYYY-MM-DD` subcommand (3D)
# ─────────────────────────────────────────────────────────────────────────────


def _parse_since(arg: str) -> Optional[date]:
    """Parse --since as ISO date YYYY-MM-DD. Returns None on malformed."""
    try:
        return date.fromisoformat(arg)
    except ValueError:
        return None


async def _cmd_backfill(args: argparse.Namespace) -> int:
    """
    Forward-only date-banded recovery (design v1.1 §6, LOCKED Q3).

    Operator-explicit recovery for the gap between the legacy producer's
    last write (2026-03-25) and the legal_mail_ingester's first patrol.

    Two modes:
      - Plan (default, no --confirm):
        Connects, runs SEARCH SINCE <date>, prints UID count + intent,
        no DB writes, no body fetches.
      - Execute (--confirm):
        Fetches up to --limit messages, parses, classifies, writes
        bilaterally, emits events. Same idempotency as patrol path
        (file_path UNIQUE constraint dedups already-ingested messages).

    Hard floor BACKFILL_HARD_FLOOR = 2026-03-26 — any earlier --since is
    rejected (would re-process Captain-handled messages from before the
    legacy producer outage). To extend, edit the constant in the service.

    \\Seen flag is NEVER mutated (BODY.PEEK[]) — Captain coexistence holds
    even during backfill.
    """
    # ── 1. Parse --since ─────────────────────────────────────────────────
    since = _parse_since(args.since)
    if since is None:
        print(
            f"ERROR: --since {args.since!r} is not a valid ISO date (YYYY-MM-DD)",
            file=sys.stderr,
        )
        return 9

    # ── 2. Hard floor enforcement ────────────────────────────────────────
    if since < BACKFILL_HARD_FLOOR:
        print(
            f"ERROR: --since {since.isoformat()} is before BACKFILL_HARD_FLOOR "
            f"{BACKFILL_HARD_FLOOR.isoformat()}",
            file=sys.stderr,
        )
        print(
            "  The legacy producer last wrote on 2026-03-25; pre-floor backfill "
            "would re-process Captain-handled messages.",
            file=sys.stderr,
        )
        print(
            "  To extend: edit BACKFILL_HARD_FLOOR in backend/services/legal_mail_ingester.py",
            file=sys.stderr,
        )
        return 10

    # ── 3. Future-date rejection ─────────────────────────────────────────
    today = date.today()
    if since > today:
        print(
            f"ERROR: --since {since.isoformat()} is in the future (today is {today.isoformat()})",
            file=sys.stderr,
        )
        return 11

    # ── 4. Mailbox alias validation ──────────────────────────────────────
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
            "only imap backfills are supported",
            file=sys.stderr,
        )
        return 5

    # ── 5. Pause warning (advisory — operator may proceed anyway) ────────
    paused = await _is_mailbox_paused(alias)
    if paused:
        print(
            f"NOTE: mailbox {alias!r} is currently paused. Backfill will proceed "
            f"(operator-explicit override) but the patrol loop will continue to skip it "
            f"until 'fgp legal mail resume --mailbox {alias}'.",
            file=sys.stderr,
        )

    # ── 6. Build transport ───────────────────────────────────────────────
    try:
        transport = LegalMailIngesterTransport(cfg)
    except (ValueError, LegalMailboxConfigError) as exc:
        print(f"ERROR: transport setup failed: {exc}", file=sys.stderr)
        return 6

    # ── 7. Plan header ───────────────────────────────────────────────────
    print(f"\nBackfill — mailbox={alias!r} ({INGESTER_VERSIONED})")
    print(f"  host:        {cfg.host}:{cfg.port}")
    print(f"  folder:      {cfg.folder}")
    print(f"  since:       {since.isoformat()} (hard floor {BACKFILL_HARD_FLOOR.isoformat()} ✓)")
    print(f"  limit:       {args.limit}")
    print(f"  routing tag: {cfg.routing_tag}")
    print()

    # ── 8. Plan mode (default — no --confirm) ────────────────────────────
    if not args.confirm:
        print("Connecting (plan mode — no body fetch, no DB writes)…")
        try:
            count = await asyncio.to_thread(transport.search_count_for_backfill, since)
        except LegalMailboxConfigError as exc:
            print(f"ERROR: credential resolution failed: {exc}", file=sys.stderr)
            return 7
        except Exception as exc:
            print(f"ERROR: SEARCH failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 8
        print(f"  ✓ SEARCH SINCE {since.isoformat()}: {count} messages match")
        print()
        print("This is a plan. To execute the backfill (writes to email_archive + event_log):")
        print(
            f"  fgp legal mail backfill --mailbox {alias} --since {since.isoformat()} "
            f"--limit {args.limit} --confirm"
        )
        print()
        print("Backfill will:")
        print("  - parse each message (header + body)")
        print("  - classify Stage 1 (priority/case/watchdog)")
        print("  - write to email_archive (bilateral; deduped via file_path UNIQUE)")
        print("  - emit email.received event to legal.event_log")
        print("  - NOT mutate IMAP \\Seen flag (BODY.PEEK[])")
        return 0

    # ── 9. Execute mode (--confirm) ──────────────────────────────────────
    print("Connecting (execute mode — bilateral writes will occur)…")
    try:
        records = await asyncio.to_thread(
            transport.fetch_for_backfill, since, args.limit,
        )
    except LegalMailboxConfigError as exc:
        print(f"ERROR: credential resolution failed: {exc}", file=sys.stderr)
        return 7
    except Exception as exc:
        print(f"ERROR: backfill fetch failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 8

    fetched = len(records)
    print(f"  ✓ fetched {fetched} message(s) (limit was {args.limit})")
    if fetched == 0:
        print()
        print("No messages to ingest. Done.")
        return 0

    # Load classifier rules once
    print("  ✓ loading classifier rules…")
    priority_sender_rules = await _load_priority_sender_rules()
    watchdog_rules = await _load_watchdog_rules()

    print()
    print(f"Processing {fetched} messages…")
    print("-" * 100)

    ingested = 0
    deduped = 0
    errored = 0
    watchdog_matches = 0
    events_emitted = 0
    t0 = time.monotonic()

    # Mirror patrol_mailbox()'s per-message loop; idempotency via file_path
    # UNIQUE handles already-ingested messages (write_email_archive_bilateral
    # returns the existing id on conflict).
    for i, record in enumerate(records, start=1):
        uid = record.get("uid", "?")
        try:
            parsed = parse_message(
                raw_bytes=record["raw_bytes"],
                source=record,
                routing_tag=cfg.routing_tag,
            )
            if parsed is None:
                errored += 1
                print(f"  [{i:>4}/{fetched}]  uid {uid:>8}  PARSE_FAILED")
                continue

            classify_inbound(parsed, priority_sender_rules, watchdog_rules)

            # Pre-check: does a row with this file_path already exist?
            # file_path is UNIQUE on email_archive, so this is the
            # authoritative dedup signal. Doing the check explicitly
            # (vs inferring from write return value) lets us report
            # accurate fresh/dedup counts AND avoid emitting a duplicate
            # email.received event for messages already in email_archive.
            async with LegacySession() as db:
                r = await db.execute(
                    text(
                        "SELECT id, ingested_from FROM email_archive "
                        "WHERE file_path = :fp"
                    ),
                    {"fp": parsed.file_path},
                )
                existing = r.fetchone()

            if existing is not None:
                deduped += 1
                tag = f"DEDUPED (id={existing.id}, ingested_from={existing.ingested_from})"
                print(f"  [{i:>4}/{fetched}]  uid {uid:>8}  {tag}")
                continue

            # Fresh — perform bilateral write + emit event
            if parsed.watchdog_matches:
                watchdog_matches += len(parsed.watchdog_matches)

            email_archive_id = await write_email_archive_bilateral(parsed)
            if email_archive_id is None:
                errored += 1
                print(f"  [{i:>4}/{fetched}]  uid {uid:>8}  WRITE_FAILED")
                continue

            ingested += 1
            event_id = await emit_email_received_event(parsed, email_archive_id)
            if event_id is not None:
                events_emitted += 1
            tag = "INGESTED"
            if parsed.watchdog_matches:
                tag += f" [+{len(parsed.watchdog_matches)} wd]"
            print(f"  [{i:>4}/{fetched}]  uid {uid:>8}  {tag}")
        except Exception as exc:
            errored += 1
            print(f"  [{i:>4}/{fetched}]  uid {uid:>8}  ERROR: {type(exc).__name__}: {str(exc)[:80]}")

    duration = time.monotonic() - t0

    print("-" * 100)
    print()
    print(f"Backfill complete — mailbox={alias!r}")
    print(f"  fetched:        {fetched}")
    print(f"  ingested:       {ingested}")
    print(f"  deduped:        {deduped}")
    print(f"  errored:        {errored}")
    print(f"  watchdog hits:  {watchdog_matches}")
    print(f"  events emitted: {events_emitted}")
    print(f"  duration:       {duration:.1f}s")
    print()
    if errored == 0:
        print("All messages processed without errors. \\Seen flag NOT mutated.")
        return 0
    print(f"NOTE: {errored} message(s) failed. Check logs for details.")
    return 0  # backfill is best-effort; partial success is not a CLI failure


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

    # backfill: forward-only recovery for the legacy producer outage gap
    p_backfill = sub.add_parser(
        "backfill",
        help="Forward-only date-banded recovery (default plan mode; --confirm to execute)",
    )
    p_backfill.add_argument("--mailbox", required=True,
                            help="Mailbox alias to backfill")
    p_backfill.add_argument("--since", required=True,
                            help="ISO date YYYY-MM-DD; hard floor 2026-03-26 per design v1.1 §6")
    p_backfill.add_argument("--limit", type=int, default=200,
                            help="Maximum messages to process this invocation (default: 200)")
    p_backfill.add_argument("--confirm", action="store_true",
                            help="Required to execute writes; without this flag, plan-only")
    p_backfill.set_defaults(func=_cmd_backfill)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
