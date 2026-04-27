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
