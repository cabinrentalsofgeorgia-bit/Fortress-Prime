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
import json as _json
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
