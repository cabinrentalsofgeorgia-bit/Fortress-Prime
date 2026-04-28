# FLOS Phase 1-2 — Dispatcher Worker Skeleton (Implementation Spec)

**Status:** PROPOSED — operator review pending before Phase 1-2A
**Author:** assistant (with operator)
**Date:** 2026-04-27
**Parent design:** `FLOS-phase-1-state-store-design-v1.1.md` (LOCKED, all Q1–Q5 closed)
**Stacks on:** Phase 1-1 schema (PR #249), which stacks on Phase 0a-3 → 0a-2 → 0a-1
**Sequencing:** Phase 1-2 follows Phase 1-1 merge

---

## 1. Goals + scope boundary

Phase 1-2 ships the **dispatcher worker skeleton** — the code that polls `legal.event_log`, dispatches to handlers, and records attempt outcomes. The skeleton is **inert by default** (`LEGAL_DISPATCHER_ENABLED=false`) and ships with **zero live handlers**: `_HANDLERS = {}` per Q5 LOCKED Option B.

**In scope:**
- Polling loop with cadence-stable sleep
- Per-event dispatch with attempt recording
- Retry budget enforcement via `dispatcher_event_attempts` count
- Dead-letter emission when retries exhausted
- Bilateral writes (fortress_db + fortress_prod) for all mutations
- Three-level error boundary (per-event / per-cycle / per-loop)
- arq job registration gated on env flag

**Out of scope (deferred to Phase 1-3):**
- Live handler implementations (`email.received`, `watchdog.matched`, `operator.input`, `dispatcher.dead_letter`)
- `case_posture` writes — no handler in 1-2 means no handler can mutate `case_posture`
- Operator CLI (`fgp legal dispatcher status / pause / resume / replay`) — Phase 1-4
- Health endpoint (`/api/internal/legal/dispatcher/health`) — Phase 1-4

**Out of scope (deferred to Phase 1-2b optimization):**
- Postgres LISTEN/NOTIFY wake-up signal. Polling-only is correct on its own (design v1.1 §7); LISTEN/NOTIFY is added later if 24h soak shows lag matters.

---

## 2. File structure

| file | role | new/modified |
|---|---|---|
| `backend/services/legal_dispatcher.py` | dispatcher worker — polling, dispatch, attempt recording, dead-letter emission | NEW |
| `backend/core/config.py` | `legal_dispatcher_enabled: bool = False` env-var binding | MODIFIED |
| `backend/core/worker.py` | arq registration block mirroring `legal_mail_ingester` (added in Phase 0a-2 §11) | MODIFIED |

No new tables, no new migrations (Phase 1-1 schema is the foundation). No CLI files (Phase 1-4). No HTTP routers (Phase 1-4).

---

## 3. Module structure — `backend/services/legal_dispatcher.py`

Single-file layout per **Q5 LOCKED Option B**. Follows `legal_mail_ingester.py` conventions exactly — same constants pattern, same dataclass shapes, same import ordering, same Session reuse from `ediscovery_agent` + `legal_mail_ingester`.

### 3.1 Module constants (top of file)

```
DISPATCHER_NAME      = "legal_dispatcher"
DISPATCHER_VERSION   = "v1"
DISPATCHER_VERSIONED = f"{DISPATCHER_NAME}:{DISPATCHER_VERSION}"   # "legal_dispatcher:v1"
DEAD_LETTER_TAG      = f"{DISPATCHER_NAME}:dead_letter"             # event_log.processed_by on dead-letter

BATCH_SIZE             = 50    # Q2 LOCKED
POLL_INTERVAL_SEC      = 5     # PROPOSED — operator may revise before 1-5 cutover
MAX_ERROR_MESSAGE_LEN  = 500   # truncate handler exception strings to this length
DEAD_LETTER_EVENT_TYPE = "dispatcher.dead_letter"
```

`DISPATCHER_VERSIONED` is the canonical identifier used in:
- `legal.event_log.processed_by` (matches the existing CHECK regex `^[a-z_]+:[a-z0-9_.-]+$`)
- All structured log events emitted by this module

### 3.2 Imports (reuse Phase 0a-2 plumbing)

```
import asyncio
import importlib
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
import structlog

from backend.core.config import settings
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_mail_ingester import ProdSession   # already exported

logger = structlog.get_logger(DISPATCHER_NAME)
```

`LegacySession` and `ProdSession` are already exported from Phase 0a-2 — no new session factories. The dispatcher inherits the same async DB engine pair the mail ingester uses.

### 3.3 Dataclasses

```
@dataclass(frozen=True)
class DispatchResult:
    """Per-event outcome from dispatch_event()."""
    event_id: int
    event_type: str
    outcome: str               # 'success' | 'error' | 'skipped' | 'dead_letter'
    attempt_number: int
    duration_ms: int
    error_message: Optional[str] = None

@dataclass
class PatrolResult:
    """Single-cycle aggregate from patrol_dispatcher()."""
    fetched: int = 0
    succeeded: int = 0
    errored: int = 0
    skipped: int = 0
    dead_lettered: int = 0
    duration_ms: int = 0
    paused: bool = False
```

Mirror of `legal_mail_ingester.PatrolResult` shape — keeps observability conventions consistent across the two control-plane services.

### 3.4 Module-level state

```
_HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}
```

**Empty in Phase 1-2.** Phase 1-3 populates it. The skeleton already uses `_HANDLERS` for in-process lookup as a fast path; if a handler isn't in the dict, the dispatcher falls back to dynamic import via `_import_handler()` (§5).

---

## 4. Polling SQL — `_fetch_unprocessed_events()`

Per design v1.1 §5.1 (LOCKED). Single SELECT against `legal.event_log` joined with the retry-budget exclusion sub-query.

```sql
SELECT id, event_type, case_slug, event_payload, emitted_at, emitted_by
FROM legal.event_log el
WHERE processed_at IS NULL
  AND id NOT IN (
      SELECT event_id
      FROM legal.dispatcher_event_attempts dea
      JOIN legal.dispatcher_routes dr ON dr.event_type = el.event_type
      WHERE dea.event_id = el.id
      GROUP BY event_id, dr.max_retries
      HAVING COUNT(*) >= dr.max_retries
  )
ORDER BY emitted_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
```

Notes:
- The exclusion sub-query reads attempt counts AND the route's `max_retries` in one expression — no separate cache; the join cost is ~50 events × (1 attempt-count read) per cycle, well within budget.
- `FOR UPDATE SKIP LOCKED` permits horizontal scaling (Phase 2+ multiple dispatcher workers) without double-processing. Costs nothing for single-worker Phase 1.
- `ORDER BY emitted_at ASC` is chronological FIFO; the `idx_event_log_unprocessed` partial index from Phase 0a-1 covers this.

The implementation wraps the query in `LegacySession()` (canonical read-side; production mirror catches up via the writer-side bilateral pattern, §8).

---

## 5. Per-event dispatch logic — `dispatch_event()`

Per design v1.1 §5.2 (LOCKED). The function is the heart of Phase 1-2.

### 5.1 Route lookup — `_load_routes()` cache

`_load_routes()` is invoked **once per cycle** at the top of `patrol_dispatcher()`. It returns a `dict[event_type → DispatcherRoute]` from `legal.dispatcher_routes`. Mirrors `legal_mail_ingester._load_priority_sender_rules()` (Phase 0a-2 §6.5) for the same reason: per-cycle pre-load avoids 50× DB reads inside the inner loop.

```python
@dataclass(frozen=True)
class DispatcherRoute:
    event_type: str
    handler_module: str
    handler_function: str
    enabled: bool
    max_retries: int

async def _load_routes() -> dict[str, DispatcherRoute]:
    async with LegacySession() as db:
        r = await db.execute(text("""
            SELECT event_type, handler_module, handler_function, enabled, max_retries
            FROM legal.dispatcher_routes
        """))
        return {row.event_type: DispatcherRoute(**row._asdict()) for row in r.fetchall()}
```

### 5.2 Dispatch flow

For each event in the batch:

1. Look up `route = routes.get(event.event_type)`.
2. If `route is None` → `_mark_skipped(event_id, reason="no_route")`. Continue.
3. If `route.enabled is False` → `_mark_skipped(event_id, reason="route_disabled")`. Continue.
4. `attempt_number` = `(SELECT COUNT(*) FROM dispatcher_event_attempts WHERE event_id = :eid) + 1`
5. `started_at = monotonic()`
6. Look up handler:
   - First in `_HANDLERS[event.event_type]` (Phase 1-3+ populated)
   - Fallback: `_import_handler(route.handler_module, route.handler_function)` (dynamic dotted-path import via `importlib.import_module` + `getattr`)
   - Phase 1-2 has no entries in `_HANDLERS`, so every dispatch falls through to dynamic import — and since handlers don't exist yet, every event will record `outcome='error'` with an `ImportError`. **This is intentional**: with the flag off (default), no events are dispatched anyway. The skeleton's behavior under flag-on with no handlers is defined and observable.
7. `try: result = await handler(event)` → `_record_attempt(event_id, attempt_number, outcome='success', duration_ms, error_message=None)` → `_mark_processed(event_id, processed_by=f"{route.handler_module}.{route.handler_function}", result=result)`
8. `except Exception as exc:` →
   - `error_message = str(exc)[:MAX_ERROR_MESSAGE_LEN]`
   - `_record_attempt(event_id, attempt_number, outcome='error', duration_ms, error_message)`
   - if `attempt_number >= route.max_retries`: → `_maybe_dead_letter(event, route, exc)` (§6)

### 5.3 `_record_attempt()` — bilateral

```python
async def _record_attempt(event_id, attempt_number, outcome, duration_ms, error_message):
    insert_sql = text("""
        INSERT INTO legal.dispatcher_event_attempts
            (event_id, attempt_number, outcome, error_message, duration_ms, attempted_at)
        VALUES (:event_id, :attempt_number, :outcome, :error_message, :duration_ms, NOW())
        RETURNING id
    """)
    # Legacy (canonical)
    async with LegacySession() as db:
        r = await db.execute(insert_sql, params); rec = r.fetchone(); legacy_id = rec.id
        await db.commit()

    # Forced-id mirror to fortress_prod (same pattern as Phase 0a-2 §10
    # write_email_archive_bilateral)
    try:
        async with ProdSession() as prod:
            await prod.execute(text("""
                INSERT INTO legal.dispatcher_event_attempts
                    (id, event_id, attempt_number, outcome, error_message, duration_ms, attempted_at)
                VALUES (:id, :event_id, :attempt_number, :outcome, :error_message, :duration_ms, NOW())
                ON CONFLICT (id) DO NOTHING
            """), {**params, "id": legacy_id})
            await prod.execute(text("""
                SELECT setval('legal.dispatcher_event_attempts_id_seq',
                              GREATEST(:id, (SELECT last_value FROM legal.dispatcher_event_attempts_id_seq)))
            """), {"id": legacy_id})
            await prod.commit()
    except Exception as exc:
        logger.warning("legal_dispatcher_attempt_mirror_failed",
                       legacy_id=legacy_id, error=str(exc)[:200])
```

The forced-id + `setval` pattern is exactly Phase 0a-2's `write_email_archive_bilateral()` discipline — preserves monotonic sequence advance even when one side falls behind.

---

## 6. Dead-letter pattern — `_maybe_dead_letter()`

Per design v1.1 §5.4 (LOCKED). Triggered when `attempt_number >= route.max_retries`.

Atomic per-event sequence (each step bilateral):

1. **Final attempt row** — already inserted in §5.3 with `outcome='error'`. Also insert a sentinel row with `outcome='dead_letter'`:
   ```sql
   INSERT INTO legal.dispatcher_event_attempts
     (event_id, attempt_number, outcome, error_message, duration_ms, attempted_at)
   VALUES (:event_id, :final_attempt, 'dead_letter', :error_message, 0, NOW())
   ```

2. **Mark event_log processed** to remove from polling queue:
   ```sql
   UPDATE legal.event_log
   SET processed_at = NOW(),
       processed_by = 'legal_dispatcher:dead_letter',
       result = jsonb_build_object(
           'status', 'dead_letter',
           'final_error', :error_message,
           'attempts', :final_attempt
       )
   WHERE id = :event_id
   ```

3. **Append to long-term retained log** (`legal.dispatcher_dead_letter`):
   ```sql
   INSERT INTO legal.dispatcher_dead_letter
     (original_event_id, event_type, case_slug, final_error, attempts, dead_lettered_at)
   VALUES (:event_id, :event_type, :case_slug, :error_message, :final_attempt, NOW())
   ```

4. **Emit fresh `dispatcher.dead_letter` event** so observability tooling sees it:
   ```sql
   INSERT INTO legal.event_log
     (event_type, case_slug, event_payload, emitted_at, emitted_by)
   VALUES (
     'dispatcher.dead_letter', :case_slug,
     jsonb_build_object(
       'original_event_id', :event_id,
       'original_event_type', :event_type,
       'final_error', :error_message,
       'attempts', :final_attempt
     ),
     NOW(),
     'legal_dispatcher:v1'
   )
   ```

   The new event re-enters the queue; its handler (Phase 1-3) is observability-only and does not emit further events.

All four steps applied bilaterally (LegacySession + ProdSession) using the forced-id mirror pattern. The four steps are sequenced inside one Python coroutine but **not** inside one DB transaction — failure mid-sequence is recoverable on the next polling cycle (the polling-exclusion sub-query is idempotent).

---

## 7. Error boundary discipline (3 levels)

Mirrors `legal_mail_ingester` §1 + §11 (Phase 0a-2 PR #246).

| level | scope | behavior on exception |
|---|---|---|
| **Per-event** in `dispatch_event()` | one event | Caught; recorded as `outcome='error'`; attempt counter increments; dispatcher continues to next event in the batch |
| **Per-cycle** in `patrol_dispatcher()` | one batch (≤50 events) | Caught; logged with `legal_dispatcher_cycle_unexpected_failure`; cycle aborts cleanly; loop continues to next sleep/cycle |
| **Per-loop** in `run_legal_dispatcher_loop()` | the long-running coroutine | Outermost defensive boundary; logged with `legal_dispatcher_loop_unexpected_failure`; sleeps `POLL_INTERVAL_SEC * 4` then retries (back-off only at this outermost level) |

The per-loop boundary is what arq's task done-callback would otherwise observe; we catch + sleep + continue rather than letting the coroutine die.

---

## 8. Bilateral mirror discipline

Per ADR-001, every write hits both DBs:

| write | Phase 1-2? | bilateral pattern |
|---|---|---|
| `legal.dispatcher_event_attempts` | YES | forced-id mirror + setval (Phase 0a-2 §10 reuse) |
| `legal.event_log` UPDATE (`processed_at`/`by`/`result`) | YES (in dead-letter step 2 + success path) | UPDATE on both DBs by `id` (id is identical pre-write) |
| `legal.event_log` INSERT (dead-letter event re-emit) | YES | forced-id mirror + setval |
| `legal.dispatcher_dead_letter` | YES | forced-id mirror + setval |
| `legal.case_posture` | NO (Phase 1-3) | n/a in Phase 1-2 |
| `legal.dispatcher_pause` | NO (Phase 1-4 CLI writes; Phase 1-2 only reads) | n/a in Phase 1-2 |

Mirror failures log a warning and continue. Operator's drift-check during Phase 1-6 24h soak validates parity.

---

## 9. Cadence-stable sleep

```python
async def run_legal_dispatcher_loop():
    while True:
        if not settings.legal_dispatcher_enabled:
            logger.info("legal_dispatcher_disabled")
            await asyncio.sleep(60)   # check flag every minute when off
            continue

        cycle_started = _time.monotonic()
        try:
            await patrol_dispatcher()
        except Exception as exc:
            logger.error("legal_dispatcher_loop_unexpected_failure",
                         error=str(exc)[:500])
            await asyncio.sleep(POLL_INTERVAL_SEC * 4)
            continue

        cycle_duration = _time.monotonic() - cycle_started
        sleep_for = max(1.0, POLL_INTERVAL_SEC - cycle_duration)
        await asyncio.sleep(sleep_for)
```

Slow cycles do **not** compound lag — if a cycle takes 4.5s and `POLL_INTERVAL_SEC=5`, we sleep 1.0s (the floor) instead of pretending we slept the full 5s. If a cycle takes 7s, sleep is `max(1, 5 - 7) = 1.0s` — still a deliberate pause to avoid pegging the DB.

---

## 10. Worker registration — `backend/core/worker.py`

Mirrors the `legal_mail_ingester` block added in Phase 0a-2 (worker.py lines ~589-616 per PR #246):

```python
if settings.legal_dispatcher_enabled:
    from backend.services.legal_dispatcher import run_legal_dispatcher_loop
    task = asyncio.create_task(run_legal_dispatcher_loop())
    task.add_done_callback(_log_task_failure)  # crash visibility
    logger.info("legal_dispatcher_started", versioned=DISPATCHER_VERSIONED)
else:
    logger.info("legal_dispatcher_disabled_at_boot")
```

`_log_task_failure` is the same callback `legal_mail_ingester` uses — surfaces silent coroutine death via structured log.

`backend/core/config.py` adds:

```python
legal_dispatcher_enabled: bool = Field(
    default=False, alias="LEGAL_DISPATCHER_ENABLED"
)
```

---

## 11. Sub-phase commit decomposition

Six commits on `feat/flos-phase-1-2-dispatcher-worker` (mirrors Phase 0a-2's six-commit pattern):

| sub-phase | scope | commit boundary |
|---|---|---|
| **1-2A** | Module skeleton + imports + constants + `DispatchResult` + `PatrolResult` + empty `_HANDLERS = {}` + `DispatcherRoute` dataclass | All wiring; no DB calls yet |
| **1-2B** | `_load_routes()` + `_is_dispatcher_paused()` + `_fetch_unprocessed_events()` polling SQL with retry-exclusion sub-query | Read paths only |
| **1-2C** | `_record_attempt()` bilateral + `_import_handler()` dynamic import helper | First write paths; bilateral mirror discipline established |
| **1-2D** | `dispatch_event()` orchestration + `_mark_processed()` + `_mark_skipped()` + `_maybe_dead_letter()` (4-step sequence + `dispatcher_dead_letter` insert + re-emitted event) | Full per-event flow |
| **1-2E** | `patrol_dispatcher()` cycle + `run_legal_dispatcher_loop()` continuous loop + cadence-stable sleep + 3-level error boundary + structured logging | Top-level orchestration |
| **1-2F** | `legal_dispatcher_enabled` flag in `config.py` + arq registration block in `worker.py` | Glue; default OFF |

Each commit surfaced before the next per the established discipline.

---

## 12. Verification posture for the Phase 1-2 PR

This PR ships code only — no schema changes, no operator surface, no CI tests (those land in a separate sub-PR per the discipline established in #246).

What CAN be verified now:
- ✅ Code parses (Python syntax)
- ✅ Schema dependency intact — `legal.dispatcher_routes` + `legal.dispatcher_event_attempts` + `legal.dispatcher_dead_letter` exist (PR #249 prerequisite)
- ✅ Service dependency intact — `LegacySession` and `ProdSession` import from `backend.services.legal_mail_ingester` (PR #246 prerequisite)
- ✅ Default OFF — flag is `bool = Field(default=False, ...)`
- ✅ `_HANDLERS = {}` empty — no handler can fire even if the flag flips on
- ✅ No test rows on any DB (worker doesn't run until cutover)

What's verified by Phase 1-3:
- Live handlers populate `_HANDLERS` and `email.received` events flow through correctly
- `case_posture` rows are created on first event for active cases

What's verified by Phase 1-5 cutover + 1-6 24h soak:
- Dispatcher lag bounded
- No false-positive dead-letters
- `dispatcher_event_attempts` row growth matches event volume
- Bilateral parity holds across 3 mutator tables

---

## 13. What Phase 1-3 adds next

Five sub-phases populating `_HANDLERS`:

| sub-phase | event_type | handler | scope |
|---|---|---|---|
| **1-3A** | `email.received` | `_handle_email_received` | scoped per design v1.1 §6.1 — load case_posture, emit watchdog.matched, refresh audit timestamps |
| **1-3B** | `watchdog.matched` | `_handle_watchdog_matched` | aggregate by `rule_id` per design v1.1 §6.2 (dict, not capped list) |
| **1-3C** | `operator.input` | `_handle_operator_input` | direct case_posture mutation; full CLI surface in Phase 2+ |
| **1-3D** | `dispatcher.dead_letter` | `_handle_dead_letter` | observability sink — append to `legal.dispatcher_dead_letter` + emit no further events |
| **1-3E** | placeholder stubs | `_handle_vault_document_ingested`, `_handle_council_deliberation_complete` | both routes already seeded `enabled=FALSE` in Phase 1-1; stubs return `{"status": "placeholder_not_implemented"}` |

Phase 1-3 is the first sub-phase where `case_posture` is mutated. Principle 1 (events drive state) is enforced operationally from 1-3 forward.

---

## 14. Cross-references

- Parent (LOCKED): `FLOS-phase-1-state-store-design-v1.1.md` §5 (worker mechanics), §11 (sub-phase sequencing)
- Schema: PR #249 (`feat/flos-phase-1-1-schema`) — provides 5 tables this worker reads/writes
- Service patterns: `backend/services/legal_mail_ingester.py` (PR #246) — bilateral writes, classifier rule pre-load, three-level error boundary, arq registration shape
- Operator surface (Phase 1-4): `legal_mail_ingester_cli.py` + `legal_mail_health.py` from PR #247 — same conventions for CLI argparse + JWT health
- ADR-001 — bilateral mirror discipline
- ADR-002 — Captain + Sentinel on Spark 2 (legal_dispatcher co-locates)
- Issue #204 — alembic chain divergence (no migrations in 1-2; respected)

---

## 15. Status flag

| element | status |
|---|---|
| Module structure (§3) | **PROPOSED** — operator may iterate before 1-2A |
| Polling SQL (§4) | **LOCKED** — derives directly from design v1.1 §5.1 |
| Per-event dispatch (§5) | **LOCKED** — derives from design v1.1 §5.2 |
| Dead-letter sequence (§6) | **LOCKED** — derives from design v1.1 §5.4 |
| Error boundaries (§7) | **LOCKED** — three levels per Phase 0a-2 precedent |
| Bilateral mirror (§8) | **LOCKED** by ADR-001 |
| Cadence-stable sleep (§9) | **PROPOSED** — POLL_INTERVAL_SEC=5 may revise before 1-5 cutover |
| Worker registration (§10) | **LOCKED** — mirrors Phase 0a-2 |
| Sub-phase decomposition (§11) | **PROPOSED** — six commits 1-2A → 1-2F |
| Verification posture (§12) | **LOCKED** — same discipline as #246/#247 |

Operator review next — iterate on PROPOSED items, then authorize Phase 1-2A skeleton commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
