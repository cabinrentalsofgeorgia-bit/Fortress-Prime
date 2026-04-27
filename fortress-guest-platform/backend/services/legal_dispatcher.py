"""
legal_dispatcher.py — FLOS Phase 1 dispatcher worker.

Consumer side of the FLOS event/state architecture. Polls
legal.event_log for unprocessed rows, dispatches each event to a
handler registered in _HANDLERS, records the attempt outcome to
legal.dispatcher_event_attempts, and emits dead-letter events when
retries are exhausted.

Per FLOS Phase 1 design v1.1 (LOCKED, all Q1–Q5 closed) +
Phase 1-2 implementation spec.

Phase 1-2 sub-phases (one commit each):
  1-2A  module skeleton + imports + constants + dataclasses + empty _HANDLERS
  1-2B  _load_routes + _is_dispatcher_paused + _fetch_unprocessed_events
  1-2C  _record_attempt bilateral
  1-2D  dispatch_event + _mark_processed + _mark_skipped + _maybe_dead_letter
  1-2E  patrol_dispatcher + run_legal_dispatcher_loop
  1-2F  config flag + arq registration in worker.py

Handler resolution model (LOCKED, Phase 1-2 clarification):
  _HANDLERS is the single source of truth for event_type → handler.
  legal.dispatcher_routes columns handler_module + handler_function are
  DB-side metadata for documentation and CLI display; they are NOT used
  for runtime lookup. If _HANDLERS[event_type] is missing the dispatcher
  records a skip with reason='handler_not_registered' (not an error
  attempt — skip is the correct posture for an unregistered route).

Phase 1-2 ships with _HANDLERS empty by design. Even with the flag flipped
on, no event would reach a handler — every dispatch records a skip.
Phase 1-3 populates _HANDLERS in this same file, per Q5 LOCKED Option B.

Default OFF: gated on settings.legal_dispatcher_enabled (env
LEGAL_DISPATCHER_ENABLED). Phase 1-5 cutover is the explicit flag flip.
"""
from __future__ import annotations

import asyncio
import time as _time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import structlog
from sqlalchemy import text  # noqa: F401 — used in 1-2B onward

from backend.core.config import settings  # noqa: F401 — used in 1-2E + 1-2F
from backend.services.ediscovery_agent import LegacySession  # noqa: F401 — used in 1-2B onward
from backend.services.legal_mail_ingester import ProdSession  # noqa: F401 — used in 1-2C onward


# ─────────────────────────────────────────────────────────────────────────────
# Module identity + constants
# ─────────────────────────────────────────────────────────────────────────────


DISPATCHER_NAME = "legal_dispatcher"
DISPATCHER_VERSION = "v1"
DISPATCHER_VERSIONED = f"{DISPATCHER_NAME}:{DISPATCHER_VERSION}"  # legal_dispatcher:v1
DEAD_LETTER_TAG = f"{DISPATCHER_NAME}:dead_letter"  # event_log.processed_by on dead-letter

# Polling cadence + batch (Q2 LOCKED at 50; POLL_INTERVAL_SEC PROPOSED 5,
# operator may revise via env override before Phase 1-5 cutover).
BATCH_SIZE = 50
POLL_INTERVAL_SEC = 5
DISABLED_SLEEP_SEC = 60   # cadence when flag is off (cheap polling)
LOOP_BACKOFF_SEC = 20     # back-off after unexpected per-loop exception

# Per design v1.1 §5.3 — error_message column is TEXT but truncated for
# audit-row sanity.
MAX_ERROR_MESSAGE_LEN = 500

DEAD_LETTER_EVENT_TYPE = "dispatcher.dead_letter"

# event_log.processed_by format must match the Phase 0a-1 CHECK regex
# ^[a-z_]+:[a-z0-9_.-]+$ — DISPATCHER_VERSIONED satisfies this.

logger = structlog.get_logger(DISPATCHER_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Outcome / route dataclasses
# ─────────────────────────────────────────────────────────────────────────────


# legal.dispatcher_event_attempts.outcome CHECK is in (success, error, dead_letter).
# 'skipped' is the in-process result for events with no registered handler or
# a route disabled in the dispatcher_routes table; skipped events do NOT write
# a dispatcher_event_attempts row (they were never attempted).
OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_DEAD_LETTER = "dead_letter"
OUTCOME_SKIPPED = "skipped"  # in-process only; not a dispatcher_event_attempts row


SKIP_REASON_NO_ROUTE = "no_route"
SKIP_REASON_ROUTE_DISABLED = "route_disabled"
SKIP_REASON_HANDLER_NOT_REGISTERED = "handler_not_registered"


@dataclass(frozen=True)
class DispatchResult:
    """Per-event outcome from dispatch_event(). Used by patrol_dispatcher
    to aggregate cycle results."""
    event_id: int
    event_type: str
    outcome: str  # success | error | dead_letter | skipped
    attempt_number: int
    duration_ms: int
    error_message: Optional[str] = None
    skip_reason: Optional[str] = None


@dataclass
class PatrolResult:
    """Single-cycle aggregate from patrol_dispatcher(). Mutable so the
    cycle can accumulate counts as events stream through."""
    fetched: int = 0
    succeeded: int = 0
    errored: int = 0
    skipped: int = 0
    dead_lettered: int = 0
    duration_ms: int = 0
    paused: bool = False
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatcherRoute:
    """In-memory row from legal.dispatcher_routes, loaded once per cycle by
    _load_routes() (added in Phase 1-2B). handler_module + handler_function
    are kept as fields for CLI display and audit; runtime lookup goes
    through _HANDLERS (in-file dict), not via dynamic import."""
    event_type: str
    handler_module: str
    handler_function: str
    enabled: bool
    max_retries: int


# ─────────────────────────────────────────────────────────────────────────────
# Handler registry (Q5 LOCKED Option B — single-file, in-process callables)
# ─────────────────────────────────────────────────────────────────────────────
#
# _HANDLERS is the canonical event_type → handler resolution.
# legal.dispatcher_routes table is metadata only; it is consulted for
# enabled/max_retries/audit but the actual callable comes from this dict.
#
# Phase 1-2 keeps this dict empty by design — no handlers ship in this
# sub-phase. Phase 1-3 sub-phases 1-3A through 1-3E populate it with:
#   "email.received"                  → _handle_email_received
#   "watchdog.matched"                → _handle_watchdog_matched
#   "operator.input"                  → _handle_operator_input
#   "dispatcher.dead_letter"          → _handle_dead_letter
#   "vault.document_ingested"         → _handle_vault_document_ingested  (placeholder)
#   "council.deliberation_complete"   → _handle_council_deliberation_complete  (placeholder)
#
# Handler signature: async def handler(event: dict) -> dict
#   - event: row dict from legal.event_log SELECT
#   - return: jsonb-serializable result for legal.event_log.result column
#
# When _HANDLERS.get(event_type) returns None, the dispatcher marks the
# event skipped with reason='handler_not_registered' — NOT an error.
# This is the correct posture: an event we don't know how to handle is
# not a failure, it's an indication that the handler hasn't shipped yet.
# ─────────────────────────────────────────────────────────────────────────────


_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Read paths (Sub-phase 1-2B)
#
# Three queries against fortress_db (LegacySession) — all read-only:
#   1. _load_routes()              — per-cycle pre-load of dispatcher_routes
#   2. _is_dispatcher_paused()     — single-row check on dispatcher_pause
#   3. _fetch_unprocessed_events() — polling SELECT with retry-exclusion
#
# Per design v1.1 §5.1 (LOCKED). LegacySession is canonical for reads;
# fortress_prod is a forward-only mirror written through bilateral helpers
# (ProdSession), which land in 1-2C.
# ─────────────────────────────────────────────────────────────────────────────


async def _load_routes() -> dict[str, DispatcherRoute]:
    """
    Per-cycle pre-load of legal.dispatcher_routes. Returns a dict keyed by
    event_type. Phase 1-2D's dispatch_event() consults this dict for
    enabled / max_retries; the actual handler callable comes from the
    in-file _HANDLERS registry (Q5 LOCKED Option B), not from the
    handler_module + handler_function columns.

    Mirrors legal_mail_ingester._load_priority_sender_rules() (Phase 0a-2)
    in shape and intent: one query per cycle avoids N× DB reads inside the
    inner per-event loop.
    """
    select_sql = text("""
        SELECT event_type, handler_module, handler_function, enabled, max_retries
        FROM legal.dispatcher_routes
    """)
    out: dict[str, DispatcherRoute] = {}
    async with LegacySession() as db:
        result = await db.execute(select_sql)
        for row in result.fetchall():
            route = DispatcherRoute(
                event_type=row.event_type,
                handler_module=row.handler_module,
                handler_function=row.handler_function,
                enabled=bool(row.enabled),
                max_retries=int(row.max_retries),
            )
            out[route.event_type] = route
    return out


async def _is_dispatcher_paused() -> bool:
    """
    True iff legal.dispatcher_pause has its singleton row present.

    Per design v1.1 §6 the pause table is a single-row control: at most
    one row exists at a time (CHECK singleton_id = 1 enforces this).
    Pause survives worker restart; resumption is operator-explicit via
    the Phase 1-4 CLI.
    """
    check_sql = text(
        "SELECT 1 FROM legal.dispatcher_pause WHERE singleton_id = 1 LIMIT 1"
    )
    async with LegacySession() as db:
        result = await db.execute(check_sql)
        return result.scalar() is not None


async def _fetch_unprocessed_events(batch_size: int = BATCH_SIZE) -> list[dict[str, Any]]:
    """
    Poll legal.event_log for unprocessed events that have not yet exhausted
    their retry budget. Returns a list of row dicts, ordered chronologically
    (FIFO by emitted_at).

    Per design v1.1 §5.1 (LOCKED). Reads:
      - legal.event_log                  WHERE processed_at IS NULL
      - legal.dispatcher_event_attempts  for the per-event attempt count
      - legal.dispatcher_routes          for max_retries

    The retry-exclusion sub-query joins event_log against
    dispatcher_event_attempts ⋈ dispatcher_routes so events that have
    already hit their max_retries are not re-dispatched. Phase 1-2D's
    _maybe_dead_letter() sets processed_at on dead-lettered events so
    they leave the polling queue entirely; this sub-query is the
    belt-and-suspenders second-line defense.

    FOR UPDATE SKIP LOCKED reserves rows for the calling transaction so
    a future scale-out (multiple dispatcher workers) does not double-
    dispatch. For Phase 1 single-worker the lock is essentially free —
    the index covers the WHERE and there is no contention.

    The function returns plain dicts (not row objects) so the caller can
    pass payloads directly to handlers without holding a session.
    """
    select_sql = text("""
        SELECT
            id, event_type, case_slug, event_payload, emitted_at, emitted_by
        FROM legal.event_log el
        WHERE processed_at IS NULL
          AND id NOT IN (
              SELECT dea.event_id
              FROM legal.dispatcher_event_attempts dea
              JOIN legal.dispatcher_routes dr
                  ON dr.event_type = el.event_type
              WHERE dea.event_id = el.id
              GROUP BY dea.event_id, dr.max_retries
              HAVING COUNT(*) >= dr.max_retries
          )
        ORDER BY emitted_at ASC
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    """)

    out: list[dict[str, Any]] = []
    async with LegacySession() as db:
        result = await db.execute(select_sql, {"batch_size": batch_size})
        for row in result.fetchall():
            out.append({
                "id": int(row.id),
                "event_type": row.event_type,
                "case_slug": row.case_slug,
                "event_payload": row.event_payload,
                "emitted_at": row.emitted_at,
                "emitted_by": row.emitted_by,
            })
        # FOR UPDATE SKIP LOCKED holds the row lock until commit/rollback.
        # We need the events out of the lock for handler dispatch; commit
        # releases the lock immediately. Per design v1.1 §5.1 + §10:
        # the dispatcher is the only writer to event_log.processed_at, so
        # there is no race between this read and a subsequent UPDATE in
        # 1-2D's _mark_processed.
        await db.commit()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Bilateral write foundation (Sub-phase 1-2C)
#
# Per FLOS-phase-1-2 implementation spec clarification #4:
# 1-2C establishes the write-side bilateral discipline foundation. Subsequent
# 1-2D + 1-2E build on this pattern. The forced-id + setval implementation
# below mirrors Phase 0a-2 §10 write_email_archive_bilateral() in
# legal_mail_ingester.py exactly:
#
#   1. Legacy INSERT with RETURNING id, then commit                     (canonical)
#   2. ProdSession INSERT (id, ...) VALUES (:forced_id, ...)            (mirror)
#      followed by setval(seq, GREATEST(forced_id, last_value))         (sequence)
#   3. Mirror failure logs + does not raise (drift mode)                (per #3)
#
# Drift acknowledgment (LOCKED clarification #3):
# Legacy is canonical. _fetch_unprocessed_events() reads only Legacy. State
# correctness is preserved when the prod mirror lags. Drift is surfaced
# during Phase 1-6 24h soak via row-count parity check. Repair pass for
# delta rows is a Phase 1-6 add-on (operator-triggered, not automatic).
#
# Schema-shape note: dispatcher_event_attempts has no UNIQUE constraint on
# (event_id, attempt_number), so the dedup-on-conflict branch from
# write_email_archive_bilateral (where file_path is UNIQUE) is structurally
# absent here. Same bilateral discipline, simpler conflict surface.
# ─────────────────────────────────────────────────────────────────────────────


async def _record_attempt(
    event_id: int,
    attempt_number: int,
    outcome: str,
    duration_ms: Optional[int],
    error_message: Optional[str],
) -> Optional[int]:
    """
    Insert one row into legal.dispatcher_event_attempts (bilateral).

    Outcome MUST be one of OUTCOME_SUCCESS, OUTCOME_ERROR, OUTCOME_DEAD_LETTER
    — these are the values accepted by chk_dispatcher_event_attempts_outcome
    (Phase 1-1 LOCKED). OUTCOME_SKIPPED is in-process-only and must NOT be
    passed here (skipped events do not write attempt rows; the dispatcher
    treats unregistered handlers as a non-failure posture per Phase 1-2
    clarification #2).

    Returns the legacy id on success. Returns None if the legacy write fails
    (caller decides whether to abort the per-event flow). Mirror failure logs
    a warning and is NOT propagated — drift mode per clarification #3.
    """
    if outcome not in (OUTCOME_SUCCESS, OUTCOME_ERROR, OUTCOME_DEAD_LETTER):
        # Defensive guard: would otherwise hit the DB CHECK and raise. Catch
        # locally with a clear log so the source bug is obvious.
        logger.error(
            "legal_dispatcher_record_attempt_invalid_outcome",
            event_id=event_id,
            attempt_number=attempt_number,
            outcome=outcome,
        )
        return None

    # Truncate at the spec-defined boundary so the column never overflows.
    if error_message is not None and len(error_message) > MAX_ERROR_MESSAGE_LEN:
        error_message = error_message[:MAX_ERROR_MESSAGE_LEN]

    row = {
        "event_id": event_id,
        "attempt_number": attempt_number,
        "outcome": outcome,
        "error_message": error_message,
        "duration_ms": duration_ms,
    }

    # ── 1. Write to fortress_db (canonical) ─────────────────────────────
    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.dispatcher_event_attempts
                        (event_id, attempt_number, outcome, error_message,
                         duration_ms, attempted_at)
                    VALUES
                        (:event_id, :attempt_number, :outcome, :error_message,
                         :duration_ms, NOW())
                    RETURNING id
                """),
                row,
            )
            row_obj = result.fetchone()
            if row_obj is not None:
                new_id = int(row_obj.id)
            await db.commit()
    except Exception as exc:
        logger.error(
            "legal_dispatcher_attempt_db_failed",
            event_id=event_id,
            attempt_number=attempt_number,
            outcome=outcome,
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        # RETURNING produced no row but no exception — should not happen on
        # an unconstrained INSERT against this table. Defensive log only.
        logger.warning(
            "legal_dispatcher_attempt_no_id_returned",
            event_id=event_id,
            attempt_number=attempt_number,
        )
        return None

    # ── 2. Mirror to fortress_prod with forced matching id ─────────────
    # Per ADR-001 + design v1.1 §10 + clarification #4. Legacy commit has
    # already happened; mirror failure logs the drift and returns the
    # canonical id anyway. State correctness rides on Legacy.
    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.dispatcher_event_attempts
                        (id, event_id, attempt_number, outcome, error_message,
                         duration_ms, attempted_at)
                    VALUES
                        (:forced_id, :event_id, :attempt_number, :outcome,
                         :error_message, :duration_ms, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                mirror_row,
            )
            # Advance the prod sequence so future autogenerated ids don't
            # collide with our forced ones. setval(seq, GREATEST(N, current))
            # is idempotent + monotonic; running twice with same N is a no-op.
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.dispatcher_event_attempts_id_seq',
                        GREATEST(
                            :forced_id,
                            (SELECT last_value FROM legal.dispatcher_event_attempts_id_seq)
                        )
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_attempt_prod_mirror_failed",
            attempt_id=new_id,
            event_id=event_id,
            attempt_number=attempt_number,
            error=str(exc)[:300],
        )
        # Mirror drift acknowledged — Phase 1-6 24h soak surfaces; repair
        # pass is operator-triggered Phase 1-6 add-on. Return Legacy id.

    return new_id
