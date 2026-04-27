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
import hashlib
import json as _json
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


# ─────────────────────────────────────────────────────────────────────────────
# Per-event orchestration + dead-letter sequence (Sub-phase 1-2D)
#
# Per design v1.1 §5.2 (dispatch flow) + §5.4 (dead-letter pattern).
# Per FLOS-phase-1-2 implementation spec §5 + §6.
#
# Resilience note on the 4-step dead-letter sequence:
#
# By the time _maybe_dead_letter is called, dispatch_event has already
# recorded the final error attempt via _record_attempt(). attempt_count
# is now >= route.max_retries, so _fetch_unprocessed_events()'s exclusion
# sub-query already excludes the event from future polling cycles.
#
# This means the event has effectively left the queue BEFORE the 4-step
# sequence begins. If any step fails mid-sequence, the event is in limbo:
# excluded from polling, not in dispatcher_dead_letter, no observability
# event emitted. Operator detects this via a Phase 1-6 24h soak query:
#
#   SELECT el.id FROM legal.event_log el
#   WHERE processed_at IS NULL
#     AND id IN (SELECT event_id FROM legal.dispatcher_event_attempts
#                GROUP BY event_id
#                HAVING COUNT(*) >= max_retries_for(event_type));
#
# Step ordering is chosen for resilience:
#   1. _record_attempt (sentinel dead_letter row) — metric correctness
#   2. _mark_processed (event_log UPDATE)         — clean queue exit
#   3. _insert_dead_letter_log                    — long-term audit
#   4. _emit_dead_letter_event                    — observability re-emit
#
# Each step is bilateral on its own; failures log + continue. Phase 2+
# can wrap steps 1+2 in one transaction if the limbo edge case proves
# operationally relevant during the 24h soak.
# ─────────────────────────────────────────────────────────────────────────────


async def _mark_skipped(
    event_id: int,
    event_type: str,
    reason: str,
) -> DispatchResult:
    """
    In-process skip marker. Per Phase 1-2 clarification #2: skips do NOT
    write a dispatcher_event_attempts row — skip is the correct posture
    for an unregistered handler / disabled route / unknown event type, not
    a failure. The event stays in legal.event_log with processed_at = NULL.

    Caller (dispatch_event) returns the DispatchResult to the patrol loop;
    PatrolResult.skip_reasons aggregates per-reason counts for operator
    surface.

    Limbo note: under flag-on-without-handlers, every event is skipped on
    every cycle and the polling SQL keeps returning the same events
    forever. This is wasteful but defined and observable. Phase 1-2 ships
    with the flag OFF by default; Phase 1-3 ships handlers before any
    operator-initiated cutover (Phase 1-5).
    """
    logger.info(
        "legal_dispatcher_event_skipped",
        event_id=event_id,
        event_type=event_type,
        reason=reason,
    )
    return DispatchResult(
        event_id=event_id,
        event_type=event_type,
        outcome=OUTCOME_SKIPPED,
        attempt_number=0,
        duration_ms=0,
        skip_reason=reason,
    )


async def _get_next_attempt_number(event_id: int) -> int:
    """
    Compute the next attempt_number for an event by counting prior rows in
    legal.dispatcher_event_attempts. 1-indexed (first attempt returns 1).

    Cheap query — idx_dispatcher_event_attempts_event_id covers the WHERE.
    Each event has at most max_retries (5) rows so the count is trivial.
    """
    async with LegacySession() as db:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM legal.dispatcher_event_attempts "
                "WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        )
        return int(result.scalar() or 0) + 1


async def _mark_processed(
    event_id: int,
    processed_by: str,
    result_payload: Optional[dict[str, Any]],
) -> bool:
    """
    UPDATE legal.event_log to mark an event processed (success or
    dead-letter path). Bilateral.

    processed_by must match the Phase 0a-1 CHECK regex
    ^[a-z_]+:[a-z0-9_.-]+$ — DISPATCHER_VERSIONED for success path,
    DEAD_LETTER_TAG for dead-letter path.

    result_payload is JSONB — passed as a Python dict and serialized
    via SQLAlchemy + asyncpg JSONB binding (same idiom as Phase 0a-2
    legal_mail_ingester event_log emission).

    Returns True iff the legacy UPDATE succeeded. Mirror failures log
    a warning (drift mode per clarification #3); the legacy success is
    the operative state-effect signal.
    """
    update_sql = text("""
        UPDATE legal.event_log
        SET processed_at = NOW(),
            processed_by = :processed_by,
            result = CAST(:result_json AS jsonb)
        WHERE id = :event_id
    """)
    params = {
        "event_id": event_id,
        "processed_by": processed_by,
        "result_json": _json.dumps(result_payload) if result_payload is not None else None,
    }

    # ── Legacy (canonical) ──────────────────────────────────────────────
    legacy_ok = False
    try:
        async with LegacySession() as db:
            await db.execute(update_sql, params)
            await db.commit()
        legacy_ok = True
    except Exception as exc:
        logger.error(
            "legal_dispatcher_mark_processed_db_failed",
            event_id=event_id,
            processed_by=processed_by,
            error=str(exc)[:300],
        )
        return False

    # ── Mirror to fortress_prod ─────────────────────────────────────────
    try:
        async with ProdSession() as prod:
            await prod.execute(update_sql, params)
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_mark_processed_prod_mirror_failed",
            event_id=event_id,
            processed_by=processed_by,
            error=str(exc)[:300],
        )
        # Mirror drift — Phase 1-6 24h soak surfaces.

    return legacy_ok


async def _insert_dead_letter_log(
    original_event_id: int,
    event_type: str,
    case_slug: Optional[str],
    final_error: str,
    attempts: int,
) -> Optional[int]:
    """
    Append a row to legal.dispatcher_dead_letter — the long-term retained
    audit log. Bilateral. Operator-triggered purge only (Q3 LOCKED).

    Step 3 of the 4-step dead-letter sequence. Same forced-id + setval
    pattern as _record_attempt (1-2C).

    Returns legacy id on success; None on legacy failure. Mirror failure
    logs + does not raise (drift mode).
    """
    if final_error and len(final_error) > MAX_ERROR_MESSAGE_LEN:
        final_error = final_error[:MAX_ERROR_MESSAGE_LEN]

    row = {
        "original_event_id": original_event_id,
        "event_type": event_type,
        "case_slug": case_slug,
        "final_error": final_error,
        "attempts": attempts,
    }

    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.dispatcher_dead_letter
                        (original_event_id, event_type, case_slug,
                         final_error, attempts, dead_lettered_at)
                    VALUES
                        (:original_event_id, :event_type, :case_slug,
                         :final_error, :attempts, NOW())
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
            "legal_dispatcher_dead_letter_log_db_failed",
            original_event_id=original_event_id,
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        logger.warning(
            "legal_dispatcher_dead_letter_log_no_id_returned",
            original_event_id=original_event_id,
        )
        return None

    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.dispatcher_dead_letter
                        (id, original_event_id, event_type, case_slug,
                         final_error, attempts, dead_lettered_at)
                    VALUES
                        (:forced_id, :original_event_id, :event_type, :case_slug,
                         :final_error, :attempts, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                mirror_row,
            )
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.dispatcher_dead_letter_id_seq',
                        GREATEST(
                            :forced_id,
                            (SELECT last_value FROM legal.dispatcher_dead_letter_id_seq)
                        )
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_dead_letter_log_prod_mirror_failed",
            dead_letter_id=new_id,
            original_event_id=original_event_id,
            error=str(exc)[:300],
        )

    return new_id


async def _emit_dead_letter_event(
    original_event_id: int,
    original_event_type: str,
    case_slug: Optional[str],
    final_error: str,
    attempts: int,
) -> Optional[int]:
    """
    Step 4 of the 4-step dead-letter sequence. Inserts a fresh
    'dispatcher.dead_letter' event into legal.event_log so observability
    tooling sees the dead-letter in the same surface as every other event.
    Phase 1-3D's dead-letter handler reads these rows.

    Bilateral with forced-id + setval — same pattern as _record_attempt and
    _insert_dead_letter_log.

    The new event_log row's emitted_by is DISPATCHER_VERSIONED (this
    service is the producer of the dead-letter event). The original
    event's processed_by — set in step 2 by _mark_processed — uses
    DEAD_LETTER_TAG so audit can distinguish "the original event was
    closed by dead-letter" from "the original event was processed
    successfully".
    """
    if final_error and len(final_error) > MAX_ERROR_MESSAGE_LEN:
        final_error = final_error[:MAX_ERROR_MESSAGE_LEN]

    payload = {
        "original_event_id": original_event_id,
        "original_event_type": original_event_type,
        "final_error": final_error,
        "attempts": attempts,
    }

    row = {
        "event_type": DEAD_LETTER_EVENT_TYPE,
        "case_slug": case_slug,
        "event_payload_json": _json.dumps(payload),
        "emitted_by": DISPATCHER_VERSIONED,
    }

    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.event_log
                        (event_type, case_slug, event_payload, emitted_at, emitted_by)
                    VALUES
                        (:event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
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
            "legal_dispatcher_dead_letter_event_db_failed",
            original_event_id=original_event_id,
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        logger.warning(
            "legal_dispatcher_dead_letter_event_no_id_returned",
            original_event_id=original_event_id,
        )
        return None

    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.event_log
                        (id, event_type, case_slug, event_payload,
                         emitted_at, emitted_by)
                    VALUES
                        (:forced_id, :event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
                    ON CONFLICT (id) DO NOTHING
                """),
                mirror_row,
            )
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.event_log_id_seq',
                        GREATEST(
                            :forced_id,
                            (SELECT last_value FROM legal.event_log_id_seq)
                        )
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_dead_letter_event_prod_mirror_failed",
            dead_letter_event_id=new_id,
            original_event_id=original_event_id,
            error=str(exc)[:300],
        )

    return new_id


async def _maybe_dead_letter(
    event: dict[str, Any],
    final_attempt_number: int,
    error_message: str,
) -> None:
    """
    Orchestrate the 4-step dead-letter sequence per design v1.1 §5.4.

    Steps execute in this order (chosen for resilience — see module-level
    note above):
      1. INSERT sentinel dispatcher_event_attempts row outcome='dead_letter'
         (metric correctness — drives dead_lettered_last_hour aggregation)
      2. UPDATE event_log SET processed_at=NOW(), processed_by=DEAD_LETTER_TAG,
         result=jsonb({status, final_error, attempts})
         (clean queue exit; even if steps 3+4 fail, event is no longer pending)
      3. INSERT into dispatcher_dead_letter (long-term retained log)
      4. INSERT new 'dispatcher.dead_letter' event into event_log
         (observability re-emit; Phase 1-3D handler is the consumer)

    Each step is bilateral. Failures log + continue to the next step.
    Phase 1-6 24h soak surfaces any partial-completion limbo via the
    operator-detectable query documented above.

    No return value — this is a fire-and-record orchestration. Caller
    (dispatch_event) returns DispatchResult with outcome=OUTCOME_DEAD_LETTER
    based on the same exception that triggered _maybe_dead_letter.
    """
    event_id = int(event["id"])
    event_type = str(event["event_type"])
    case_slug = event.get("case_slug")

    # The sentinel row uses a NEW attempt_number (final_attempt_number + 1)
    # so it does not collide with the final error row that dispatch_event
    # already wrote. Storing it as a separate row preserves the audit:
    # operator can read the final error attempt's error_message AND see the
    # explicit dead_letter outcome row.
    sentinel_attempt_number = final_attempt_number + 1

    # ── Step 1: sentinel attempt row ────────────────────────────────────
    sentinel_id = await _record_attempt(
        event_id=event_id,
        attempt_number=sentinel_attempt_number,
        outcome=OUTCOME_DEAD_LETTER,
        duration_ms=0,
        error_message=error_message,
    )
    if sentinel_id is None:
        logger.error(
            "legal_dispatcher_dead_letter_step1_failed",
            event_id=event_id,
            event_type=event_type,
        )

    # ── Step 2: mark event_log processed ────────────────────────────────
    truncated_error = (
        error_message[:MAX_ERROR_MESSAGE_LEN]
        if error_message and len(error_message) > MAX_ERROR_MESSAGE_LEN
        else error_message
    )
    result_payload: dict[str, Any] = {
        "status": "dead_letter",
        "final_error": truncated_error,
        "attempts": final_attempt_number,
    }
    processed_ok = await _mark_processed(
        event_id=event_id,
        processed_by=DEAD_LETTER_TAG,
        result_payload=result_payload,
    )
    if not processed_ok:
        logger.error(
            "legal_dispatcher_dead_letter_step2_failed",
            event_id=event_id,
            event_type=event_type,
        )

    # ── Step 3: append to dispatcher_dead_letter ───────────────────────
    log_id = await _insert_dead_letter_log(
        original_event_id=event_id,
        event_type=event_type,
        case_slug=case_slug,
        final_error=truncated_error or "",
        attempts=final_attempt_number,
    )
    if log_id is None:
        logger.error(
            "legal_dispatcher_dead_letter_step3_failed",
            event_id=event_id,
            event_type=event_type,
        )

    # ── Step 4: emit dispatcher.dead_letter event ──────────────────────
    new_event_id = await _emit_dead_letter_event(
        original_event_id=event_id,
        original_event_type=event_type,
        case_slug=case_slug,
        final_error=truncated_error or "",
        attempts=final_attempt_number,
    )
    if new_event_id is None:
        logger.error(
            "legal_dispatcher_dead_letter_step4_failed",
            event_id=event_id,
            event_type=event_type,
        )

    logger.info(
        "legal_dispatcher_event_dead_lettered",
        event_id=event_id,
        event_type=event_type,
        attempts=final_attempt_number,
        dispatcher_dead_letter_id=log_id,
        dead_letter_event_id=new_event_id,
    )


async def dispatch_event(
    event: dict[str, Any],
    routes: dict[str, DispatcherRoute],
) -> DispatchResult:
    """
    Per-event orchestration. The heart of the dispatcher.

    Per design v1.1 §5.2 + implementation spec §5.

    Flow:
      1. Route lookup in `routes` dict (pre-loaded once per cycle by
         _load_routes() in 1-2B; passed in by the patrol loop in 1-2E).
      2. If no route → mark_skipped(no_route).
      3. If route disabled → mark_skipped(route_disabled).
      4. Handler lookup in _HANDLERS (Q5 LOCKED Option B + clarification #1).
      5. If handler not registered → mark_skipped(handler_not_registered).
         No DB write. Phase 1-2 ships with _HANDLERS empty so every
         dispatch falls through here when the flag is on.
      6. Compute next attempt_number from dispatcher_event_attempts count.
      7. Run handler with wall-clock timing.
      8. On success: _record_attempt(success) + _mark_processed.
      9. On exception: _record_attempt(error). If attempt_number reaches
         route.max_retries → _maybe_dead_letter (4-step sequence).

    Per-event try/except is the per-event error boundary (one of three
    levels per implementation spec §7); _record_attempt + _mark_processed
    have their own internal error handling and never raise.
    """
    event_id = int(event["id"])
    event_type = str(event["event_type"])

    # ── 1. Route lookup ─────────────────────────────────────────────────
    route = routes.get(event_type)
    if route is None:
        return await _mark_skipped(event_id, event_type, SKIP_REASON_NO_ROUTE)

    # ── 2. Enabled check ────────────────────────────────────────────────
    if not route.enabled:
        return await _mark_skipped(event_id, event_type, SKIP_REASON_ROUTE_DISABLED)

    # ── 3. Handler lookup (in-file _HANDLERS only — no dynamic import) ──
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return await _mark_skipped(
            event_id, event_type, SKIP_REASON_HANDLER_NOT_REGISTERED
        )

    # ── 4. Compute attempt_number ───────────────────────────────────────
    attempt_number = await _get_next_attempt_number(event_id)

    # ── 5. Run handler with timing ──────────────────────────────────────
    started_at = _time.monotonic()
    try:
        result = await handler(event)
        duration_ms = int((_time.monotonic() - started_at) * 1000)

        await _record_attempt(
            event_id=event_id,
            attempt_number=attempt_number,
            outcome=OUTCOME_SUCCESS,
            duration_ms=duration_ms,
            error_message=None,
        )
        # Handler return value is the legal.event_log.result payload.
        # Defensive coercion (LOCKED Phase 1-2D revision):
        #   dict   → as-is
        #   None   → {}              (handler completed but produced no payload)
        #   other  → {"value": ...}  (defensive wrap for non-dict scalars)
        result_payload: dict[str, Any]
        if isinstance(result, dict):
            result_payload = result
        elif result is None:
            result_payload = {}
        else:
            result_payload = {"value": result}
        await _mark_processed(
            event_id=event_id,
            processed_by=DISPATCHER_VERSIONED,
            result_payload=result_payload,
        )

        return DispatchResult(
            event_id=event_id,
            event_type=event_type,
            outcome=OUTCOME_SUCCESS,
            attempt_number=attempt_number,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        duration_ms = int((_time.monotonic() - started_at) * 1000)
        error_message = str(exc)

        await _record_attempt(
            event_id=event_id,
            attempt_number=attempt_number,
            outcome=OUTCOME_ERROR,
            duration_ms=duration_ms,
            error_message=error_message,
        )

        # Retry budget check. attempt_number is 1-indexed; max_retries is
        # the number of attempts allowed before dead-letter. With max_retries=5
        # the 5th attempt is the last try; on its failure we dead-letter.
        if attempt_number >= route.max_retries:
            await _maybe_dead_letter(
                event=event,
                final_attempt_number=attempt_number,
                error_message=error_message,
            )
            return DispatchResult(
                event_id=event_id,
                event_type=event_type,
                outcome=OUTCOME_DEAD_LETTER,
                attempt_number=attempt_number,
                duration_ms=duration_ms,
                error_message=(
                    error_message[:MAX_ERROR_MESSAGE_LEN]
                    if len(error_message) > MAX_ERROR_MESSAGE_LEN
                    else error_message
                ),
            )

        return DispatchResult(
            event_id=event_id,
            event_type=event_type,
            outcome=OUTCOME_ERROR,
            attempt_number=attempt_number,
            duration_ms=duration_ms,
            error_message=(
                error_message[:MAX_ERROR_MESSAGE_LEN]
                if len(error_message) > MAX_ERROR_MESSAGE_LEN
                else error_message
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level orchestration (Sub-phase 1-2E)
#
# Per FLOS-phase-1-2 implementation spec §5 + §7 + §9.
#
# Three-level error boundary (mirrors legal_mail_ingester precedent):
#
#   Per-event   in dispatch_event()           — handler exception caught;
#               (1-2D)                          recorded as outcome='error';
#                                               dispatcher continues to next
#                                               event in the batch.
#
#   Per-cycle   in patrol_dispatcher()        — unexpected exception in cycle
#               (this sub-phase)                (e.g. DB connection drop);
#                                               cycle aborts cleanly; loop
#                                               continues to next sleep/cycle.
#
#   Per-loop    in run_legal_dispatcher_loop  — outermost defensive boundary
#               (this sub-phase)                for the long-running coroutine;
#                                               sleeps LOOP_BACKOFF_SEC then
#                                               retries. Back-off only at
#                                               this level.
#
# Cadence-stable sleep — slow cycles do NOT compound lag. If a cycle takes
# longer than POLL_INTERVAL_SEC, we sleep the floor (1.0s) instead of
# pretending we slept the full interval. See run_legal_dispatcher_loop().
# ─────────────────────────────────────────────────────────────────────────────


async def patrol_dispatcher() -> PatrolResult:
    """
    Single-cycle batch processing. Per implementation spec §5 + design v1.1 §5.

    Sequence:
      0. Pause check (skip cycle if dispatcher_pause has its singleton row)
      1. Load routes (once per cycle)
      2. Fetch up to BATCH_SIZE unprocessed events (with retry-budget exclusion)
      3. dispatch_event() per event; aggregate PatrolResult
      4. Emit per-cycle structured log

    Returns the PatrolResult so the caller (the loop) can decide cadence
    based on whether the cycle did real work. Errors from any single event
    are absorbed by dispatch_event's per-event boundary; this function's
    outer try/except is the per-cycle boundary for unexpected DB-level
    failures (connection drops, transaction conflicts, etc.).
    """
    result = PatrolResult()
    cycle_started_monotonic = _time.monotonic()

    try:
        # ── 0. Pause check ──────────────────────────────────────────────
        if await _is_dispatcher_paused():
            result.paused = True
            result.duration_ms = int((_time.monotonic() - cycle_started_monotonic) * 1000)
            logger.info(
                "legal_dispatcher_cycle_paused",
                duration_ms=result.duration_ms,
            )
            return result

        # ── 1. Load routes (once per cycle) ────────────────────────────
        routes = await _load_routes()

        # ── 2. Fetch batch ──────────────────────────────────────────────
        events = await _fetch_unprocessed_events(batch_size=BATCH_SIZE)
        result.fetched = len(events)

        # ── 3. Per-event dispatch ──────────────────────────────────────
        for event in events:
            dispatch_result = await dispatch_event(event, routes)
            if dispatch_result.outcome == OUTCOME_SUCCESS:
                result.succeeded += 1
            elif dispatch_result.outcome == OUTCOME_ERROR:
                result.errored += 1
            elif dispatch_result.outcome == OUTCOME_DEAD_LETTER:
                result.dead_lettered += 1
            elif dispatch_result.outcome == OUTCOME_SKIPPED:
                result.skipped += 1
                if dispatch_result.skip_reason:
                    result.skip_reasons[dispatch_result.skip_reason] = (
                        result.skip_reasons.get(dispatch_result.skip_reason, 0) + 1
                    )
            else:
                # Defensive — should never reach here unless dispatch_event
                # is changed to emit a new outcome value without updating
                # this aggregator. Log so the source bug is obvious.
                logger.error(
                    "legal_dispatcher_unknown_outcome",
                    event_id=dispatch_result.event_id,
                    outcome=dispatch_result.outcome,
                )

    except Exception as exc:
        # Per-cycle boundary. Logs and lets the loop sleep+retry. Events
        # already dispatched in this cycle keep their state-effects
        # (per-event work commits as it goes); the unprocessed remainder
        # of the batch returns to the polling queue automatically since
        # _fetch_unprocessed_events committed its FOR UPDATE lock on
        # release.
        logger.error(
            "legal_dispatcher_cycle_unexpected_failure",
            error=str(exc)[:500],
            error_type=type(exc).__name__,
            partial_succeeded=result.succeeded,
            partial_errored=result.errored,
            partial_skipped=result.skipped,
            partial_dead_lettered=result.dead_lettered,
        )

    result.duration_ms = int((_time.monotonic() - cycle_started_monotonic) * 1000)

    # ── 4. Per-cycle structured log ────────────────────────────────────
    logger.info(
        "legal_dispatcher_cycle_report",
        fetched=result.fetched,
        succeeded=result.succeeded,
        errored=result.errored,
        skipped=result.skipped,
        dead_lettered=result.dead_lettered,
        skip_reasons=result.skip_reasons,
        duration_ms=result.duration_ms,
        paused=result.paused,
    )

    return result


async def run_legal_dispatcher_loop() -> None:
    """
    Continuous patrol loop. Started by fortress-arq-worker on boot
    (registered in Sub-phase 1-2F backend/core/worker.py block, gated on
    settings.legal_dispatcher_enabled).

    Cadence-stable sleep per implementation spec §9: slow cycles do NOT
    compound lag. The sleep formula `max(1.0, POLL_INTERVAL_SEC - elapsed)`
    keeps a 1-second floor so a 10-second cycle still pauses briefly
    between iterations (avoids pegging the DB on a permanently slow
    workload).

    Per-loop error boundary is the outermost defensive layer. Any exception
    that escapes patrol_dispatcher's per-cycle boundary lands here; we log,
    sleep LOOP_BACKOFF_SEC, and continue. The coroutine is intended to run
    for the full lifetime of the arq worker process — never returns under
    normal conditions.

    Default OFF: when settings.legal_dispatcher_enabled is False, the loop
    sleeps DISABLED_SLEEP_SEC and re-checks. This lets the operator flip
    the env flag without restarting the worker (Phase 1-5 cutover may use
    a worker restart anyway, but the polling-flag pattern is consistent
    with legal_mail_ingester).
    """
    logger.info(
        "legal_dispatcher_loop_started",
        versioned=DISPATCHER_VERSIONED,
        batch_size=BATCH_SIZE,
        poll_interval_sec=POLL_INTERVAL_SEC,
    )

    while True:
        if not settings.legal_dispatcher_enabled:
            logger.info(
                "legal_dispatcher_disabled",
                next_check_sec=DISABLED_SLEEP_SEC,
            )
            await asyncio.sleep(DISABLED_SLEEP_SEC)
            continue

        cycle_start = _time.monotonic()
        try:
            await patrol_dispatcher()
        except Exception as exc:
            # Per-loop boundary — defensive. patrol_dispatcher has its own
            # per-cycle try/except, so this catches only escaped or
            # framework-level failures (e.g. asyncio runtime errors).
            logger.error(
                "legal_dispatcher_loop_unexpected_failure",
                error=str(exc)[:500],
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(LOOP_BACKOFF_SEC)
            continue

        cycle_duration = _time.monotonic() - cycle_start
        sleep_for = max(1.0, POLL_INTERVAL_SEC - cycle_duration)
        await asyncio.sleep(sleep_for)


# ─────────────────────────────────────────────────────────────────────────────
# Event handlers — Phase 1-3 (Q5 LOCKED Option B in-file callables)
#
# Per FLOS-phase-1-3-event-handlers-implementation.md.
#
# Phase 1-3 is the first sub-phase where legal.case_posture is mutated.
# Principle 1 (events drive state) is enforced operationally from this
# sub-phase forward: the dispatcher is the only writer to case_posture;
# every mutation cites updated_by_event for Principle 4 audit attribution.
#
# Sub-phase scope:
#   1-3A (this commit) — shared helpers + email.received handler
#   1-3B               — watchdog.matched handler (consumes 1-3A re-emissions)
#   1-3C               — operator.input handler with allowlist
#   1-3D               — dispatcher.dead_letter handler (observability only)
#   1-3E               — placeholder stubs + populate _HANDLERS dict
#
# Handler signature (LOCKED):
#   async def _handle_<event_type>(event: dict[str, Any]) -> dict[str, Any]
# Returns a JSONB-serializable result dict for legal.event_log.result.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (Sub-phase 1-3A)
# ─────────────────────────────────────────────────────────────────────────────


# Phase 1 canonicalization input set for posture_hash. Order is fixed; the
# JSON serialization uses sort_keys=True so dict ordering is irrelevant, but
# the SET of fields below is what defines hash semantics. Phase 2+ field
# additions append to this list (and the field set is versioned in code via
# the explicit constant; design v1.1 §3 PROPOSED a posture_hash_version
# column add — deferred unless drift detection proves necessary).
_POSTURE_HASH_FIELDS: tuple[str, ...] = (
    "case_slug",
    "procedural_phase",
    "theory_of_defense_state",
    "top_defense_arguments",
    "top_risk_factors",
)


# Whitelist of case_posture columns the dispatcher may write via
# _bilateral_write_case_posture. Broader than OPERATOR_INPUT_ALLOWED_FIELDS
# (1-3C scope) because the dispatcher writes more fields than operators
# (e.g. 1-3B updates top_risk_factors; 1-3C operator.input cannot).
#
# NOT INCLUDED (system-managed; set automatically by the helper):
#   case_slug          — WHERE clause; never updated
#   created_at         — DEFAULT NOW() at INSERT only
#   updated_at         — set automatically on every UPDATE
#   posture_hash       — recomputed automatically on every UPDATE
#   created_by_event   — set on INSERT only; immutable thereafter
#   updated_by_event   — set automatically on every UPDATE
_CASE_POSTURE_WRITABLE_FIELDS: frozenset[str] = frozenset({
    "procedural_phase",
    "theory_of_defense_state",
    "next_deadline_date",
    "next_deadline_action",
    "top_defense_arguments",
    "top_risk_factors",
    "exposure_low",
    "exposure_mid",
    "exposure_high",
    "leverage_score",
    "opposing_counsel_profile",
    "last_council_consensus",
    "last_council_at",
})

# Columns that need explicit JSONB binding when written via raw SQL. Other
# columns use direct parameter binding; SQLAlchemy + asyncpg handle the rest.
_CASE_POSTURE_JSONB_FIELDS: frozenset[str] = frozenset({
    "top_defense_arguments",
    "top_risk_factors",
    "opposing_counsel_profile",
    "last_council_consensus",
})


def _compute_posture_hash(posture: dict[str, Any]) -> str:
    """
    SHA-256 over a JSON-canonicalized projection of the Phase 1-populated
    fields per design v1.1 §3 + spec §3.3 LOCKED.

    The canonicalization input set is fixed at five fields:
      case_slug, procedural_phase, theory_of_defense_state,
      top_defense_arguments, top_risk_factors

    Phase 2+ field additions extend _POSTURE_HASH_FIELDS in code; if the
    set changes we may need a posture_hash_version column add to detect
    cross-version drift, but that's deferred unless operationally relevant.

    JSON canonicalization: sort_keys=True + compact separators ensures
    identical input dicts produce identical hash output regardless of
    Python dict ordering or whitespace.
    """
    canonical_input = {field: posture.get(field) for field in _POSTURE_HASH_FIELDS}
    canonical_json = _json.dumps(
        canonical_input, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


async def _case_exists_in_legal_cases(case_slug: str) -> bool:
    """
    Verify case_slug references a row in legal.cases.

    Phase 1-3A scope: existence check only. legal.cases has a `status`
    column but no documented "active" status enum yet — operator may
    refine this to a status-based filter in 1-3B+ if needed (e.g.
    `WHERE case_slug = :slug AND status NOT IN ('closed', 'archived')`).
    For Phase 1-3A, any row in legal.cases is sufficient.
    """
    async with LegacySession() as db:
        result = await db.execute(
            text("SELECT 1 FROM legal.cases WHERE case_slug = :slug LIMIT 1"),
            {"slug": case_slug},
        )
        return result.scalar() is not None


async def _load_or_create_case_posture(
    case_slug: str,
    event_id: int,
) -> Optional[dict[str, Any]]:
    """
    Load the existing case_posture row OR create a fresh row with Phase 1-1
    schema defaults. Returns the row as a dict, or None if case_slug does
    not match a row in legal.cases.

    Returns None (NOT a stub posture) when the case is not found — caller
    decides whether to skip-no-active-case or surface the miss. This keeps
    the helper a pure read-or-create primitive without per-handler policy
    leaks.

    Defaults applied on CREATE (matches Phase 1-1 schema CHECK constraints):
      procedural_phase = 'pre-suit'
      theory_of_defense_state = 'drafting'
      top_defense_arguments = []
      top_risk_factors = {}
      created_by_event = updated_by_event = event_id
      posture_hash = _compute_posture_hash(canonical_input)

    Bilateral on CREATE: legacy INSERT first, prod mirror second. Mirror
    failure logs warning and does NOT raise (drift mode per Phase 1-2
    clarification #3 LOCKED).

    Idempotency: re-call with same case_slug returns the existing row;
    the create path is taken at most once per case.
    """
    select_sql = text("""
        SELECT case_slug, procedural_phase, next_deadline_date,
               next_deadline_action, theory_of_defense_state,
               top_defense_arguments, top_risk_factors,
               exposure_low, exposure_mid, exposure_high, leverage_score,
               opposing_counsel_profile, last_council_consensus,
               last_council_at, posture_hash, created_at, updated_at,
               created_by_event, updated_by_event
        FROM legal.case_posture
        WHERE case_slug = :slug
    """)

    # ── 1. Try load ─────────────────────────────────────────────────────
    async with LegacySession() as db:
        result = await db.execute(select_sql, {"slug": case_slug})
        row = result.fetchone()
        if row is not None:
            return dict(row._mapping)

    # ── 2. Verify case is a valid matter ────────────────────────────────
    if not await _case_exists_in_legal_cases(case_slug):
        logger.info(
            "legal_dispatcher_case_posture_skip_unknown_case",
            case_slug=case_slug,
            event_id=event_id,
        )
        return None

    # ── 3. Create new row with defaults ─────────────────────────────────
    fresh_posture = {
        "case_slug": case_slug,
        "procedural_phase": "pre-suit",
        "theory_of_defense_state": "drafting",
        "top_defense_arguments": [],
        "top_risk_factors": {},
    }
    new_hash = _compute_posture_hash(fresh_posture)

    insert_sql = text("""
        INSERT INTO legal.case_posture
            (case_slug, procedural_phase, theory_of_defense_state,
             top_defense_arguments, top_risk_factors,
             posture_hash, created_at, updated_at,
             created_by_event, updated_by_event)
        VALUES
            (:case_slug, 'pre-suit', 'drafting',
             CAST(:top_defense_arguments AS jsonb),
             CAST(:top_risk_factors AS jsonb),
             :posture_hash, NOW(), NOW(),
             :event_id, :event_id)
        ON CONFLICT (case_slug) DO NOTHING
    """)
    insert_params = {
        "case_slug": case_slug,
        "top_defense_arguments": _json.dumps([]),
        "top_risk_factors": _json.dumps({}),
        "posture_hash": new_hash,
        "event_id": event_id,
    }

    # ── 3a. Legacy (canonical) INSERT ────────────────────────────────────
    try:
        async with LegacySession() as db:
            await db.execute(insert_sql, insert_params)
            await db.commit()
    except Exception as exc:
        logger.error(
            "legal_dispatcher_case_posture_create_db_failed",
            case_slug=case_slug,
            event_id=event_id,
            error=str(exc)[:300],
        )
        return None

    # ── 3b. Prod mirror INSERT (drift mode) ──────────────────────────────
    # case_posture PK is case_slug (TEXT), not BIGSERIAL — so there is no
    # sequence to setval. ON CONFLICT (case_slug) DO NOTHING handles a
    # second-mirror scenario (e.g. partial mirror retry) idempotently.
    try:
        async with ProdSession() as prod:
            await prod.execute(insert_sql, insert_params)
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_case_posture_create_prod_mirror_failed",
            case_slug=case_slug,
            event_id=event_id,
            error=str(exc)[:300],
        )
        # Drift mode — Phase 1-6 24h soak surfaces.

    # ── 4. Re-read so caller sees the canonical row (timestamps + hash) ─
    async with LegacySession() as db:
        result = await db.execute(select_sql, {"slug": case_slug})
        row = result.fetchone()
        if row is not None:
            return dict(row._mapping)

    # Race condition or DB failure between INSERT and SELECT — log and
    # return None so caller bails cleanly.
    logger.error(
        "legal_dispatcher_case_posture_post_create_select_failed",
        case_slug=case_slug,
        event_id=event_id,
    )
    return None


async def _bilateral_write_case_posture(
    case_slug: str,
    updates: dict[str, Any],
    event_id: int,
) -> bool:
    """
    UPDATE the case_posture row with the supplied field map. Bilateral
    (legacy first, prod mirror second). Always sets updated_by_event,
    updated_at, posture_hash.

    Per Phase 1-3 spec §3.2 + §10 mutation discipline LOCKED:
      - Cite updated_by_event = event_id (Principle 4 source attribution)
      - Bump updated_at = NOW()
      - Recompute posture_hash AFTER all field mutations applied
      - Bilateral (mirror failure logs + does not raise — drift mode)

    Empty `updates` dict is valid: the function still bumps the audit
    timestamps + recomputes posture_hash. That's the "1-3A timestamp-only
    refresh" semantic for email.received events that don't change state
    fields (per §4 LOCKED scope).

    Field validation: keys in `updates` are validated against
    _CASE_POSTURE_WRITABLE_FIELDS. Unknown keys log error and the call
    aborts before touching the DB. This is the second line of defense
    against bad input; the first is per-handler validation (e.g.
    1-3C OPERATOR_INPUT_ALLOWED_FIELDS, which is a stricter subset).

    Returns True iff the legacy UPDATE succeeded.
    """
    # ── 1. Validate field keys ──────────────────────────────────────────
    invalid = [k for k in updates if k not in _CASE_POSTURE_WRITABLE_FIELDS]
    if invalid:
        logger.error(
            "legal_dispatcher_case_posture_invalid_field_keys",
            case_slug=case_slug,
            invalid_keys=invalid,
            event_id=event_id,
        )
        return False

    # ── 2. Re-read current state to compute new posture_hash ───────────
    select_sql = text("""
        SELECT case_slug, procedural_phase, theory_of_defense_state,
               top_defense_arguments, top_risk_factors
        FROM legal.case_posture
        WHERE case_slug = :slug
    """)
    async with LegacySession() as db:
        result = await db.execute(select_sql, {"slug": case_slug})
        current = result.fetchone()
        if current is None:
            logger.error(
                "legal_dispatcher_case_posture_update_no_row",
                case_slug=case_slug,
                event_id=event_id,
            )
            return False
        # Apply pending updates over current state for hash purposes.
        merged = dict(current._mapping)
        merged.update(updates)
    new_hash = _compute_posture_hash(merged)

    # ── 3. Build dynamic UPDATE SET clause ──────────────────────────────
    # Keys come from _CASE_POSTURE_WRITABLE_FIELDS (validated above), so
    # f-string interpolation here is safe — no user-supplied column names.
    set_clauses: list[str] = []
    params: dict[str, Any] = {
        "case_slug": case_slug,
        "event_id": event_id,
        "new_hash": new_hash,
    }
    for key, value in updates.items():
        if key in _CASE_POSTURE_JSONB_FIELDS:
            set_clauses.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = _json.dumps(value) if value is not None else None
        else:
            set_clauses.append(f"{key} = :{key}")
            params[key] = value
    # Always include audit columns
    set_clauses.append("updated_by_event = :event_id")
    set_clauses.append("updated_at = NOW()")
    set_clauses.append("posture_hash = :new_hash")

    update_sql = text(
        "UPDATE legal.case_posture SET "
        + ", ".join(set_clauses)
        + " WHERE case_slug = :case_slug"
    )

    # ── 4. Legacy (canonical) UPDATE ────────────────────────────────────
    try:
        async with LegacySession() as db:
            await db.execute(update_sql, params)
            await db.commit()
    except Exception as exc:
        logger.error(
            "legal_dispatcher_case_posture_update_db_failed",
            case_slug=case_slug,
            event_id=event_id,
            error=str(exc)[:300],
        )
        return False

    # ── 5. Prod mirror UPDATE (drift mode) ──────────────────────────────
    try:
        async with ProdSession() as prod:
            await prod.execute(update_sql, params)
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_case_posture_update_prod_mirror_failed",
            case_slug=case_slug,
            event_id=event_id,
            error=str(exc)[:300],
        )

    return True


async def _emit_watchdog_event(
    case_slug: str,
    match: dict[str, Any],
    source_event_id: int,
) -> Optional[int]:
    """
    Emit a fresh watchdog.matched event into legal.event_log. Used by
    _handle_email_received to re-route watchdog match payloads to
    _handle_watchdog_matched (Phase 1-3B handler).

    Bilateral with forced-id + setval pattern — same shape as
    _emit_dead_letter_event (1-2D §6 step 4).

    emitted_by = DISPATCHER_VERSIONED ('legal_dispatcher:v1') because the
    dispatcher is the producer of this re-emitted event. The original
    email.received event's emitted_by tag is preserved in the payload's
    source_event_id field for the audit chain.

    Returns new event_id on success; None on legacy failure. Mirror
    failure logs and continues (drift mode).
    """
    payload = {
        "rule_id": match.get("rule_id"),
        "rule_name": match.get("rule_name"),
        "severity": match.get("severity"),
        "match_type": match.get("match_type"),
        "search_term": match.get("search_term"),
        "source_event_id": source_event_id,
    }
    row = {
        "event_type": "watchdog.matched",
        "case_slug": case_slug,
        "event_payload_json": _json.dumps(payload),
        "emitted_by": DISPATCHER_VERSIONED,
    }

    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.event_log
                        (event_type, case_slug, event_payload, emitted_at, emitted_by)
                    VALUES
                        (:event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
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
            "legal_dispatcher_watchdog_event_db_failed",
            case_slug=case_slug,
            source_event_id=source_event_id,
            rule_id=match.get("rule_id"),
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        logger.warning(
            "legal_dispatcher_watchdog_event_no_id_returned",
            case_slug=case_slug,
            source_event_id=source_event_id,
        )
        return None

    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.event_log
                        (id, event_type, case_slug, event_payload,
                         emitted_at, emitted_by)
                    VALUES
                        (:forced_id, :event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
                    ON CONFLICT (id) DO NOTHING
                """),
                mirror_row,
            )
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.event_log_id_seq',
                        GREATEST(
                            :forced_id,
                            (SELECT last_value FROM legal.event_log_id_seq)
                        )
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_watchdog_event_prod_mirror_failed",
            new_event_id=new_id,
            source_event_id=source_event_id,
            error=str(exc)[:300],
        )

    return new_id


# ─────────────────────────────────────────────────────────────────────────────
# Handler 1-3A — _handle_email_received
#
# Per design v1.1 §6.1 LOCKED scope + spec §4 LOCKED.
# Triggered by legal_mail_ingester:v1 on every inbound legal email.
#
# Scope (LOCKED v1.1 §6.1):
#   1. Skip if event.case_slug is null or doesn't match an active case
#   2. Load or create case_posture row for case_slug
#   3. For each watchdog_match in event_payload, emit watchdog.matched event
#   4. Refresh case_posture audit timestamps (no field mutations)
#
# Removed from v1.1 scope (deferred to Phase 2+):
#   - procedural_phase mutation logic (operator-defined rules without an
#     operator-defined ruleset; Phase 2+ adds legal.procedural_phase_rules
#     table and a separate handler)
#
# Idempotency (Principle 6 LOCKED):
#   Same event re-applied yields same case_posture state. Re-emitted
#   watchdog events would create duplicate watchdog.matched rows — but
#   this only happens during operator-driven recovery; the dispatcher's
#   polling-exclusion sub-query (Phase 1-2 §5.1) prevents same-event
#   re-application in steady-state.
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_email_received(event: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 1-3A handler for email.received events emitted by
    legal_mail_ingester:v1 (Phase 0a-2 producer).

    See module-level comment block above for full scope rationale.

    Returns one of:
      {"status": "skipped_no_case_slug"}
      {"status": "skipped_no_active_case", "case_slug": <slug>}
      {"status": "success", "case_slug": <slug>, "watchdog_events_emitted": N}

    The dispatcher's _mark_processed (Phase 1-2 §5.2) writes this return
    dict to legal.event_log.result.
    """
    event_id = int(event["id"])
    case_slug = event.get("case_slug")
    payload = event.get("event_payload") or {}

    # ── 1. Skip checks ───────────────────────────────────────────────────
    if not case_slug:
        return {"status": "skipped_no_case_slug"}

    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {
            "status": "skipped_no_active_case",
            "case_slug": case_slug,
        }

    # ── 2. Re-emit watchdog.matched events ──────────────────────────────
    matches = payload.get("watchdog_matches") or []
    emitted = 0
    for match in matches:
        if not isinstance(match, dict):
            # Defensive: legal_mail_ingester emits watchdog_matches as a
            # list of dicts per design v1.1 §8 event_payload spec. If a
            # producer ever drifts to scalar entries, log and skip
            # rather than crash the handler.
            logger.warning(
                "legal_dispatcher_watchdog_match_non_dict",
                case_slug=case_slug,
                event_id=event_id,
            )
            continue
        new_event_id = await _emit_watchdog_event(case_slug, match, event_id)
        if new_event_id is not None:
            emitted += 1

    # ── 3. Refresh case_posture audit timestamps ────────────────────────
    # Empty updates dict triggers updated_by_event/updated_at/posture_hash
    # refresh only — no field mutations per LOCKED v1.1 §6.1.
    await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates={},
        event_id=event_id,
    )

    return {
        "status": "success",
        "case_slug": case_slug,
        "watchdog_events_emitted": emitted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Operator alert emission helper (Sub-phase 1-3B)
#
# Used by _handle_watchdog_matched when severity == 'P1'. Bilateral INSERT
# into legal.event_log with event_type='operator.alert'. Same forced-id +
# setval pattern as _emit_watchdog_event (1-3A) and _emit_dead_letter_event
# (1-2D §6 step 4).
#
# Phase 1-3 emits the event but its CONSUMER ships in Phase 2+ (operator
# alert routing — paging, notification, dashboard surface). Until the
# consumer ships, operator.alert events accumulate in event_log; the
# dispatcher's _HANDLERS dict has no entry for 'operator.alert' so each
# event records a skip with reason='handler_not_registered' (per Phase 1-2
# clarification #2 — no DB write for skips).
#
# Phase 2+ adds:
#   1. legal.dispatcher_routes seed row for 'operator.alert'
#      (handler_module=..., handler_function='handle_operator_alert',
#       enabled=TRUE)
#   2. _HANDLERS['operator.alert'] = _handle_operator_alert in this file
#   3. Operator-facing surfaces (CLI, paging, dashboard alert queue)
# ─────────────────────────────────────────────────────────────────────────────


async def _emit_operator_alert(
    case_slug: str,
    source_payload: dict[str, Any],
    source_event_id: int,
) -> Optional[int]:
    """
    Emit a fresh operator.alert event into legal.event_log. Triggered by
    1-3B handler when watchdog severity == 'P1'.

    Per spec §5 (LOCKED). The alert payload preserves the full watchdog
    match context so the Phase 2+ consumer can decide alert routing
    without rejoining the original event_log row.

    emitted_by = DISPATCHER_VERSIONED. The original watchdog event's id
    is preserved in payload.source_event_id for the audit chain
    (legal_mail_ingester → email.received → legal_dispatcher emits
    watchdog.matched → legal_dispatcher emits operator.alert).

    Returns new event_id on success; None on legacy failure. Mirror
    failure logs and continues (drift mode).
    """
    payload = {
        "rule_id": source_payload.get("rule_id"),
        "rule_name": source_payload.get("rule_name"),
        "severity": source_payload.get("severity"),
        "match_type": source_payload.get("match_type"),
        "search_term": source_payload.get("search_term"),
        "source_event_id": source_event_id,
        "alert_reason": "watchdog_severity_p1",
    }
    row = {
        "event_type": "operator.alert",
        "case_slug": case_slug,
        "event_payload_json": _json.dumps(payload),
        "emitted_by": DISPATCHER_VERSIONED,
    }

    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.event_log
                        (event_type, case_slug, event_payload, emitted_at, emitted_by)
                    VALUES
                        (:event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
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
            "legal_dispatcher_operator_alert_db_failed",
            case_slug=case_slug,
            source_event_id=source_event_id,
            rule_id=source_payload.get("rule_id"),
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        logger.warning(
            "legal_dispatcher_operator_alert_no_id_returned",
            case_slug=case_slug,
            source_event_id=source_event_id,
        )
        return None

    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.event_log
                        (id, event_type, case_slug, event_payload,
                         emitted_at, emitted_by)
                    VALUES
                        (:forced_id, :event_type, :case_slug,
                         CAST(:event_payload_json AS jsonb), NOW(), :emitted_by)
                    ON CONFLICT (id) DO NOTHING
                """),
                mirror_row,
            )
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.event_log_id_seq',
                        GREATEST(
                            :forced_id,
                            (SELECT last_value FROM legal.event_log_id_seq)
                        )
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        logger.warning(
            "legal_dispatcher_operator_alert_prod_mirror_failed",
            new_event_id=new_id,
            source_event_id=source_event_id,
            error=str(exc)[:300],
        )

    return new_id


# ─────────────────────────────────────────────────────────────────────────────
# Handler 1-3B — _handle_watchdog_matched
#
# Per design v1.1 §6.2 LOCKED scope (per-rule aggregation) + spec §5 LOCKED.
# Triggered by 1-3A re-emission when an inbound email matches one or more
# watchdog rules. Second writer to legal.case_posture in Phase 1.
#
# Aggregation contract (LOCKED v1.1 §6.2):
#   top_risk_factors is a JSONB dict keyed by rule_id. Each unique rule_id
#   occupies exactly ONE entry. Repeated matches of the same rule increment
#   match_count + update last_match_at; they do NOT create new entries.
#
# Bounded-growth property:
#   |top_risk_factors entries| <= |active watchdog rules per case|
#   Typical: 10-30 rules per case → at most 10-30 dict entries.
#   This is the LOCKED contract that distinguishes v1.1 from v1's
#   "append capped at 50" representation.
#
# Phase 1-6 24h soak verification (per spec §13):
#   - Single rule matched N times → 1 dict entry with match_count=N
#   - N distinct rules matched → N dict entries (NOT N×match_count entries)
#   - Unbounded match_count growth on a single rule entry signals replay
#     pathology (recovery operation iterating the same event)
#
# Idempotency note:
#   Re-applying the same event increments match_count by 1. Acceptable
#   because:
#     1. Polling-exclusion sub-query (Phase 1-2 §5.1) prevents
#        same-event re-application in steady state
#     2. Replay is operator-driven; match_count reflects emission count,
#        which is the desired audit semantic
#     3. Phase 1-6 24h soak detects unbounded growth as a recovery
#        red flag
#   If Phase 2+ requires stricter idempotency, switch to
#   max(match_count, current+1) or add (event_id, rule_id) UNIQUE constraint.
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_watchdog_matched(event: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 1-3B handler for watchdog.matched events emitted by
    legal_dispatcher:v1 (1-3A re-emission).

    See module-level comment block above for aggregation contract +
    bounded-growth property + idempotency rationale.

    Returns one of:
      {"status": "skipped_missing_required_fields"}
      {"status": "skipped_no_active_case", "case_slug": <slug>}
      {"status": "success", "rule_id": <id>, "match_count": <n>,
       "operator_alert_emitted": <bool>}
    """
    event_id = int(event["id"])
    case_slug = event.get("case_slug")
    payload = event.get("event_payload") or {}
    rule_id = payload.get("rule_id")

    # ── 1. Required-field validation ────────────────────────────────────
    if not case_slug or not rule_id:
        return {"status": "skipped_missing_required_fields"}

    # ── 2. Load case_posture (or create lazily) ────────────────────────
    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {
            "status": "skipped_no_active_case",
            "case_slug": case_slug,
        }

    # ── 3. Per-rule aggregation in top_risk_factors dict ───────────────
    # The dict is keyed by rule_id. Same rule_id matched N times → 1
    # entry with match_count=N. Distinct rule_ids → multiple entries.
    # Bounded by active watchdog rule count per case (~10-30 typical).
    current_factors = posture.get("top_risk_factors") or {}
    # Defensive: legacy data or migration drift might leave this as a
    # list (v1 representation) instead of a dict. Coerce + log.
    if not isinstance(current_factors, dict):
        logger.warning(
            "legal_dispatcher_top_risk_factors_unexpected_type",
            case_slug=case_slug,
            actual_type=type(current_factors).__name__,
            event_id=event_id,
        )
        current_factors = {}

    now_iso = datetime.now(timezone.utc).isoformat()
    rule_id_str = str(rule_id)
    existing = current_factors.get(rule_id_str)
    if isinstance(existing, dict):
        # Increment match_count + refresh last_match_at; preserve
        # first_match_at, severity, rule_name from the original entry.
        existing["last_match_at"] = now_iso
        existing["match_count"] = int(existing.get("match_count", 0)) + 1
        match_count = existing["match_count"]
    else:
        # New rule_id — insert fresh entry with both timestamps set to now.
        current_factors[rule_id_str] = {
            "rule_id": rule_id_str,
            "rule_name": payload.get("rule_name"),
            "severity": payload.get("severity"),
            "first_match_at": now_iso,
            "last_match_at": now_iso,
            "match_count": 1,
        }
        match_count = 1

    # ── 4. Bilateral case_posture write ─────────────────────────────────
    write_ok = await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates={"top_risk_factors": current_factors},
        event_id=event_id,
    )
    if not write_ok:
        # _bilateral_write_case_posture already logged the failure cause.
        # Return error status so dispatcher records outcome=ERROR; retry
        # budget applies and the event eventually dead-letters if the
        # condition persists.
        return {
            "status": "error_case_posture_write_failed",
            "case_slug": case_slug,
            "rule_id": rule_id_str,
        }

    # ── 5. Emit operator.alert for P1 severity ──────────────────────────
    # The alert event lands in event_log with emitted_by=DISPATCHER_VERSIONED.
    # Phase 1-3 has no _HANDLERS entry for operator.alert, so the dispatcher
    # records a handler_not_registered skip per clarification #2 (no DB
    # write for skips). Phase 2+ ships the alert handler.
    operator_alert_emitted = False
    if str(payload.get("severity") or "").upper() == "P1":
        alert_event_id = await _emit_operator_alert(
            case_slug=case_slug,
            source_payload=payload,
            source_event_id=event_id,
        )
        operator_alert_emitted = alert_event_id is not None

    return {
        "status": "success",
        "case_slug": case_slug,
        "rule_id": rule_id_str,
        "match_count": match_count,
        "operator_alert_emitted": operator_alert_emitted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Handler 1-3C — _handle_operator_input
#
# Per design v1.1 §6.3 + spec §6 + §6.1 LOCKED.
# Triggered by future operator CLI commands (Phase 2+). For Phase 1-3 the
# route is wired but live operator commands ship in Phase 2+ — only test
# fixture events exercise this handler during Phase 1-3 development.
#
# OPERATOR_INPUT_ALLOWED_FIELDS (LOCKED — operator decision):
#   procedural_phase, theory_of_defense_state, top_defense_arguments,
#   exposure_low, exposure_mid, exposure_high, leverage_score,
#   opposing_counsel_profile
#
# These 8 fields are a STRICT SUBSET of _CASE_POSTURE_WRITABLE_FIELDS (1-3A).
# Blocked fields (NOT in operator allowlist):
#   top_risk_factors            — dispatcher-managed via 1-3B aggregation;
#                                 operator override would corrupt match_count
#                                 + last_match_at semantics
#   last_council_consensus      — Phase 2+ council handler writes; protect
#   last_council_at               from operator races
#   next_deadline_date          — Phase 2+ deadline projection writes;
#   next_deadline_action          protect from operator races
#   case_slug                   — primary key, immutable
#   created_at / updated_at     — system-managed timestamps
#   posture_hash                — system-recomputed on every write
#   created_by_event /          — system-managed audit FKs
#   updated_by_event
#
# Phase 2+ may add operator.curate_risk_factor event type for emergency
# top_risk_factors curation if operationally needed; not Phase 1 scope.
#
# Event payload contract (LOCKED v1.1 §6.3):
#   {
#     "command": "set_field",
#     "case_slug": "<slug>",
#     "fields": {
#       "<field_name>": <value>,
#       ...
#     }
#   }
#
# Currently the only command is 'set_field'. Phase 2+ may add 'unset_field'
# (set NULL), 'append_to_jsonb_array', etc. — those would land as separate
# command branches in this handler, each with its own validation.
# ─────────────────────────────────────────────────────────────────────────────


# LOCKED — operator decision per Phase 1-3 spec §6.1.
OPERATOR_INPUT_ALLOWED_FIELDS: frozenset[str] = frozenset({
    "procedural_phase",
    "theory_of_defense_state",
    "top_defense_arguments",
    "exposure_low",
    "exposure_mid",
    "exposure_high",
    "leverage_score",
    "opposing_counsel_profile",
})

# Defense-in-depth assertion at module load: the operator allowlist must
# be a strict subset of the dispatcher's writable field set. If a future
# edit to either constant breaks this invariant, this assertion fires at
# import time so the source bug is obvious.
assert OPERATOR_INPUT_ALLOWED_FIELDS.issubset(_CASE_POSTURE_WRITABLE_FIELDS), (
    "OPERATOR_INPUT_ALLOWED_FIELDS must be a subset of "
    "_CASE_POSTURE_WRITABLE_FIELDS — operator cannot mutate fields the "
    "dispatcher itself does not consider writable."
)


async def _handle_operator_input(event: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 1-3C handler for operator.input events.

    Validates payload structure + command + field allowlist before
    delegating mutation to _bilateral_write_case_posture (1-3A).

    DB-layer CHECK constraints enforce enum/range values
    (procedural_phase, theory_of_defense_state, leverage_score), so
    invalid VALUES fail at the DB layer with a clear error_message
    surfaced via dispatcher_event_attempts.outcome='error'. This handler
    only validates field NAMES against the allowlist; it does not
    re-validate values that the schema already guards.

    Returns one of:
      {"status": "skipped_unknown_command", "command": <command>}
      {"status": "skipped_missing_case_slug"}
      {"status": "skipped_no_fields"}
      {"status": "skipped_no_active_case", "case_slug": <slug>}
      {"status": "rejected_invalid_fields", "invalid": [<field_names>]}
      {"status": "error_case_posture_write_failed", ...}
      {"status": "success", "case_slug": <slug>,
       "fields_updated": [<field_names>]}
    """
    event_id = int(event["id"])
    payload = event.get("event_payload") or {}

    command = payload.get("command")
    case_slug = payload.get("case_slug")
    fields = payload.get("fields") or {}

    # ── 1. Command validation ───────────────────────────────────────────
    # Phase 1-3 supports only 'set_field'. Phase 2+ may add additional
    # commands; until then, unknown commands are treated as no-ops
    # (skip, not error) so future producers don't dead-letter their
    # events while their consumer ships.
    if command != "set_field":
        return {
            "status": "skipped_unknown_command",
            "command": command,
        }

    # ── 2. Required-field validation ────────────────────────────────────
    if not case_slug:
        return {"status": "skipped_missing_case_slug"}
    if not isinstance(fields, dict) or not fields:
        return {"status": "skipped_no_fields"}

    # ── 3. Load or create case_posture ──────────────────────────────────
    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {
            "status": "skipped_no_active_case",
            "case_slug": case_slug,
        }

    # ── 4. Field allowlist validation ───────────────────────────────────
    # Reject the entire mutation set if ANY field is not in the allowlist.
    # All-or-nothing semantics: an operator command that names both
    # allowed and disallowed fields is rejected wholesale rather than
    # silently dropping the disallowed ones (which could surprise the
    # operator and leave the case_posture in a half-applied state).
    invalid = [f for f in fields if f not in OPERATOR_INPUT_ALLOWED_FIELDS]
    if invalid:
        logger.warning(
            "legal_dispatcher_operator_input_rejected_invalid_fields",
            case_slug=case_slug,
            event_id=event_id,
            invalid_fields=invalid,
        )
        return {
            "status": "rejected_invalid_fields",
            "case_slug": case_slug,
            "invalid": invalid,
        }

    # ── 5. Apply mutations ──────────────────────────────────────────────
    # _bilateral_write_case_posture handles JSONB casting (top_defense_
    # arguments, opposing_counsel_profile) automatically via
    # _CASE_POSTURE_JSONB_FIELDS. DB-layer CHECK constraints enforce
    # enum/range values; invalid values raise and are recorded as
    # outcome='error' by the dispatcher.
    write_ok = await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates=dict(fields),
        event_id=event_id,
    )
    if not write_ok:
        return {
            "status": "error_case_posture_write_failed",
            "case_slug": case_slug,
        }

    return {
        "status": "success",
        "case_slug": case_slug,
        "fields_updated": list(fields.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Handler 1-3D — _handle_dead_letter
#
# Per design v1.1 §6.6 + spec §7 LOCKED — observability ONLY.
#
# Closes the dead-letter loop. Phase 1-2 1-2D _maybe_dead_letter (step 4)
# emits a 'dispatcher.dead_letter' event into legal.event_log so this
# event surfaces in the same observability plane as every other event.
# This handler is the consumer — it surfaces the dead-letter to ops via
# structured log and writes nothing.
#
# CRITICAL constraints (LOCKED v1.1 §6.6 + spec §7):
#   - Does NOT emit further events. A failure in this handler's own
#     dispatch could itself dead-letter, which would re-emit, which
#     would re-fail, ad infinitum. Pure observability avoids the loop.
#   - Does NOT write to case_posture. Dead-letters are observability,
#     not state. case_posture mutations come from email.received +
#     watchdog.matched + operator.input only.
#   - Does NOT write to legal.dispatcher_dead_letter. Phase 1-2 1-2D
#     _insert_dead_letter_log already wrote that row in step 3 of the
#     4-step sequence. Double-writing would create duplicate audit rows.
#
# The handler's only effect is a structured log emission. The dispatcher's
# _mark_processed (Phase 1-2) writes the return dict to event_log.result.
#
# Idempotency: trivially idempotent (no state mutation; only structured
# logging). Same event re-applied produces an identical log line and an
# identical return value.
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_dead_letter(event: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 1-3D handler for dispatcher.dead_letter events emitted by
    legal_dispatcher:v1 (Phase 1-2 1-2D _maybe_dead_letter step 4).

    See module-level comment block above for the three NOT-DOES
    constraints + idempotency rationale.

    Returns the observation result. The dispatcher's _mark_processed
    writes this dict to legal.event_log.result.
    """
    event_id = int(event["id"])
    payload = event.get("event_payload") or {}

    # Structured log — the only side effect of this handler.
    # Operator surface (Phase 1-4 CLI + health endpoint) reads
    # legal.dispatcher_dead_letter for the long-term audit; this log
    # provides real-time observability via the structlog pipeline.
    logger.warning(
        "legal_dispatcher_dead_letter_observed",
        event_id=event_id,
        original_event_id=payload.get("original_event_id"),
        original_event_type=payload.get("original_event_type"),
        case_slug=event.get("case_slug"),
        final_error=payload.get("final_error"),
        attempts=payload.get("attempts"),
    )

    return {
        "status": "observed",
        "original_event_id": payload.get("original_event_id"),
    }
