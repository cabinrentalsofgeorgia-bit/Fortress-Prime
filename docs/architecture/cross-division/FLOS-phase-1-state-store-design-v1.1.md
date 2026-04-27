# FLOS Phase 1 — State Store + Event Dispatcher (v1.1)

**Status:** LOCKED — final. All Q1–Q5 closed. Phase 1-1 schema migration authorization is the next operator move.
**Author:** assistant (with operator)
**Date:** 2026-04-27
**Revision:** v1.1 — incorporates operator sharpenings on v1; closes Q1–Q5
**Parent:** `FLOS-design-v1.md` §3.1 (state store), §3.2 (event bus), §3.3 (action dispatcher), §3.5 (audit trail)
**Predecessor:** `FLOS-phase-1-state-store-design.md` (v1, preserved as review history)
**Stacks on:** Phase 0a-1 (PR #245), Phase 0a-2 (PR #246), Phase 0a-3 (PR #247)
**Sequencing:** Phase 1 follows Phase 0a end-to-end merge + Phase 0a-5 24h soak

---

## v1 → v1.1 changelog

| change | section | direction |
|---|---|---|
| Dropped `dispatcher_routes.priority` column | §4 | LOCKED — no Phase 1 use case; revisit Phase 2+ |
| Scoped down `email.received` handler — removed `procedural_phase` mutation logic | §6.1 | LOCKED — fuzzy without operator ruleset; defer to Phase 2+ |
| `top_risk_factors` aggregates by `rule_id` (dict, not capped list) | §6.2 | LOCKED — bounded by active-rule count; informative |
| `case_posture` field population annotated per phase | §3 | LOCKED — schema unchanged, inline comments added |
| Retry tracking + metrics consolidated into `legal.dispatcher_event_attempts` | §5.3 + §10 | LOCKED — single table; removed `legal_dispatcher_metrics` reference |
| Q1 procedural_phase enum | §12 | CLOSED — FLOS-design-v1 defaults LOCKED |
| Q2 batch size | §12 | CLOSED — 50 LOCKED |
| Q3 dead-letter retention | §12 | CLOSED — operator-triggered purge LOCKED + Phase 1-4 scope addition |
| Q4 versioning | §12 | CLOSED — single row + event_log audit (Option A) LOCKED |
| Q5 handler layout | §12 | CLOSED — Option B (single file with `_HANDLERS` dict) LOCKED |

---

## 1. Goals

Phase 0a established the **producer side** of FLOS: the `legal_mail_ingester` writes `email.received` events to `legal.event_log`. Events accumulate but no consumer reads them; the queue grows monotonically.

Phase 1 establishes the **consumer side**:

1. **State store (`legal.case_posture`)** — one row per active matter. Schema covers procedural phase, deadlines, exposure, leverage, theory of defense, and Council consensus. Most fields are written by Phase 2+ work; Phase 1 writes a minimal subset (see §3).
2. **Action dispatcher (`backend/services/legal_dispatcher.py`)** — a worker that polls `legal.event_log WHERE processed_at IS NULL`, dispatches each event through `legal.dispatcher_routes`, and projects state mutations into `legal.case_posture`. Updates `event_log.processed_at + processed_by + result` on completion.
3. **Operator surface** — read access to `case_posture` via CLI (`fgp legal posture get --case-slug X`) and HTTP health endpoint (`/api/internal/legal/dispatcher/health`).

The dispatcher is the **only writer** to `case_posture`. Other code paths read; they do not mutate. This is the load-bearing invariant of Phase 1 (§13 Principle 1).

`legal.event_log` already exists (Phase 0a-1, migration `q2b3c4d5e6f7`). Phase 1 adds the consumer; the producer was Phase 0a.

---

## 2. Architectural placement

### 2.1 Spark allocation (per ADR-002)

| component | spark | rationale |
|---|---|---|
| `legal_mail_ingester` (producer) | Spark 2 | LOCKED — email IMAP polling, control-plane class |
| `legal_dispatcher` (consumer) | Spark 2 | LOCKED — control-plane consumer; co-located with producer; same `fortress-arq-worker` runtime |
| `legal.case_posture` table | fortress_db (Spark 1, primary) + fortress_prod (Spark 1, mirror) | LOCKED — bilateral discipline, ADR-001 |
| Future Council deliberation triggered by dispatcher | Spark 4 | LOCKED — ADR-002, Council always Spark 4 |
| Future legal-NIM brain inference | Spark 1 | LOCKED — ADR-003 inference plane |

The dispatcher itself is small (Postgres polling + JSON dispatch). It does not run inference. Spark 2 co-location with `legal_mail_ingester` keeps the writer→consumer hop in-process latency terms (no inter-spark round trip).

### 2.2 File placement

| file | role |
|---|---|
| `backend/services/legal_dispatcher.py` | dispatcher worker — polling loop, dispatch, state mutation, **inline `_HANDLERS` dict** (Q5 LOCKED) |
| `backend/scripts/legal_dispatcher_cli.py` | operator CLI: `status`, `pause`, `resume`, `replay`, `posture get`, `dead-letter purge` |
| `backend/api/legal_dispatcher_health.py` | HTTP health endpoint at `/api/internal/legal/dispatcher/health` |
| `backend/alembic/versions/<rev>_flos_phase_1_1_case_posture_schema.py` | schema migration (Phase 1-1) |

All Phase 1 design decisions LOCKED. No further OPEN questions.

---

## 3. `legal.case_posture` schema (LOCKED)

One row per active matter, identified by `case_slug` (FK to `legal.cases.slug`).

Single migration creates all 18 fields. **Phase 1 populates a minimal subset; remaining fields are written by Phase 2+ work.** The schema exists end-to-end so Phase 2 onboarding does not require a follow-up ALTER.

| field | type | nullable | Phase 1 written? | source |
|---|---|---|---|---|
| `case_slug` | TEXT | NO | **YES** | seeded on first event for an active case |
| `procedural_phase` | TEXT | NO | **default only** | DEFAULT `'pre-suit'`; Phase 2+ writes via operator-managed rule table |
| `next_deadline_date` | DATE | YES | NO | Phase 2+ — populated by `legal.case_deadlines` projection |
| `next_deadline_action` | TEXT | YES | NO | Phase 2+ |
| `theory_of_defense_state` | TEXT | NO | **default only** | DEFAULT `'drafting'`; Phase 2+ theory-of-defense system writes |
| `top_defense_arguments` | JSONB | NO | NO | Phase 2+ — DEFAULT `'[]'` |
| `top_risk_factors` | JSONB | NO | **YES** | aggregated by `rule_id` per §6.2; DEFAULT `'{}'` |
| `exposure_low` | NUMERIC(12,2) | YES | NO | Phase 2+ — exposure model |
| `exposure_mid` | NUMERIC(12,2) | YES | NO | Phase 2+ |
| `exposure_high` | NUMERIC(12,2) | YES | NO | Phase 2+ |
| `leverage_score` | NUMERIC(4,2) | YES | NO | Phase 2+ — Council projection |
| `opposing_counsel_profile` | JSONB | YES | NO | Phase 2+ — counsel research projection |
| `last_council_consensus` | JSONB | YES | NO | Phase 2+ — `council.deliberation_complete` handler |
| `last_council_at` | TIMESTAMPTZ | YES | NO | Phase 2+ |
| `posture_hash` | TEXT | NO | **YES** | SHA-256 of canonicalized populated fields |
| `created_at` | TIMESTAMPTZ | NO | **YES** | DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NO | **YES** | refreshed on every mutation |
| `created_by_event` | BIGINT | YES | **YES** | FK to `legal.event_log.id` — first event that materialized this row |
| `updated_by_event` | BIGINT | YES | **YES** | FK to `legal.event_log.id` — most recent mutation source |

**Indexes:** PK on `case_slug`; partial index on `(next_deadline_date) WHERE next_deadline_date IS NOT NULL` for "what's due in the next N days" queries (Phase 2+ uses).

**Constraints:**
- CHECK on `procedural_phase IN ('pre-suit', 'answer-due', 'discovery', 'motion', 'trial-prep', 'settlement', 'post-trial', 'closed')` — LOCKED per Q1
- CHECK on `theory_of_defense_state IN ('drafting', 'validated', 'locked')`
- CHECK on `leverage_score BETWEEN -1.00 AND 1.00`
- FK on `updated_by_event` and `created_by_event` to `legal.event_log(id)`

**Bilateral mirror discipline (ADR-001):** every `case_posture` write hits both `fortress_db` (canonical) and `fortress_prod` (mirror), with forced matching `case_slug`. Forward-only — no schema drift between the two.

**Versioning:** Single row per case (Q4 LOCKED — Option A). Audit history reconstructs via `event_log` walk where `updated_by_event` cites the source event.

**`posture_hash` canonicalization:** SHA-256 over a JSON-canonicalized projection of the **populated** fields only. Phase 2+ field additions extend the canonicalization input; the field set is versioned (PROPOSED — `posture_hash_version` column add deferred to Phase 1-3 if drift detection is needed before Phase 2 ships those fields).

---

## 4. `legal.dispatcher_routes` schema (LOCKED)

Config-driven event-type → handler mapping. Lets the operator iterate routing rules without code changes.

| field | type | nullable | notes |
|---|---|---|---|
| `event_type` | TEXT | NO | PRIMARY KEY; matches `event_log.event_type` |
| `handler_module` | TEXT | NO | dotted path |
| `handler_function` | TEXT | NO | callable name within the module |
| `enabled` | BOOLEAN | NO | DEFAULT TRUE; allows disabling a route without deletion |
| `max_retries` | INTEGER | NO | DEFAULT 5 |
| `description` | TEXT | YES | human-readable purpose |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |

**Removed in v1.1:** the `priority` column from v1. Phase 1 has no priority-routing use case (4 live handlers, no conflict scenarios). Polling SQL stays `ORDER BY emitted_at` — chronological FIFO. Re-add `priority` in Phase 2+ if conflicts emerge.

**Initial seed rules** (Phase 1-1 migration):

| event_type | handler | enabled |
|---|---|---|
| `email.received` | `legal_dispatcher_handlers.email_received.handle` | TRUE |
| `watchdog.matched` | `legal_dispatcher_handlers.watchdog_matched.handle` | TRUE |
| `operator.input` | `legal_dispatcher_handlers.operator_input.handle` | TRUE |
| `dispatcher.dead_letter` | `legal_dispatcher_handlers.dead_letter.handle` | TRUE |
| `vault.document_ingested` | `legal_dispatcher_handlers.vault_document_ingested.handle` | FALSE |
| `council.deliberation_complete` | `legal_dispatcher_handlers.council_deliberation_complete.handle` | FALSE |

The two `enabled=FALSE` rows pre-register placeholders so the dispatcher does not log a "no_route" warning when those event types appear before their handlers ship. Activation flips to TRUE in Phase 2+.

---

## 5. Dispatcher worker mechanics

### 5.1 Polling loop

Mirrors `legal_mail_ingester`'s patrol structure:

```
async def run_legal_dispatcher_loop():
    while True:
        if not settings.legal_dispatcher_enabled:
            log("legal_dispatcher_disabled"); sleep(60); continue
        events = await fetch_unprocessed_events(limit=BATCH_SIZE)
        for event in events:
            await dispatch_event(event)  # error-isolated per-event
        await sleep(POLL_INTERVAL_SEC)
```

`BATCH_SIZE = 50` (Q2 LOCKED). `POLL_INTERVAL_SEC` PROPOSED 5s (operator may revise; not gating).

**Polling SQL** (uses Phase 0a-1's `idx_event_log_unprocessed` partial index):

```
SELECT id, event_type, case_slug, event_payload, emitted_at, emitted_by
FROM legal.event_log
WHERE processed_at IS NULL
  AND id NOT IN (
      SELECT event_id FROM legal.dispatcher_event_attempts
      GROUP BY event_id
      HAVING COUNT(*) >= (SELECT max_retries FROM legal.dispatcher_routes
                          WHERE event_type = legal.event_log.event_type)
  )
ORDER BY emitted_at
LIMIT 50
FOR UPDATE SKIP LOCKED;
```

`FOR UPDATE SKIP LOCKED` permits horizontal scaling later (multiple dispatcher workers) without double-processing. Single-worker is sufficient for Phase 1; the lock hint costs nothing now and de-risks Phase 2 scale-out.

The retry exclusion sub-query reads from `legal.dispatcher_event_attempts` (§5.3) so events past their retry budget are skipped on the SELECT side rather than dispatched-and-rejected.

### 5.2 Per-event dispatch

```
async def dispatch_event(event):
    route = get_route(event.event_type)              # legal.dispatcher_routes lookup
    if route is None or not route.enabled:
        await mark_skipped(event.id, reason="no_route" | "route_disabled")
        return
    handler = import_handler(route.handler_module, route.handler_function)
    started_at = monotonic()
    try:
        result = await handler(event)
        duration_ms = int((monotonic() - started_at) * 1000)
        await record_attempt(event.id, outcome="success", duration_ms=duration_ms)
        await mark_processed(event.id, processed_by=f"{route.handler_module}:{route.handler_function}", result=result)
    except Exception as exc:
        duration_ms = int((monotonic() - started_at) * 1000)
        await record_attempt(event.id, outcome="error", error_message=str(exc)[:500], duration_ms=duration_ms)
        await maybe_dead_letter(event.id, route.max_retries, exc)
```

### 5.3 `legal.dispatcher_event_attempts` — retry tracking + metrics (LOCKED)

**Single table for retry tracking AND metrics aggregation.** Replaces v1's split between a retry table and a separate `legal_dispatcher_metrics` table.

| field | type | nullable | notes |
|---|---|---|---|
| `id` | BIGSERIAL | NO | PK |
| `event_id` | BIGINT | NO | FK to `legal.event_log.id` |
| `attempt_number` | INTEGER | NO | 1-indexed; increments per failure |
| `outcome` | TEXT | NO | CHECK in (`success`, `error`, `dead_letter`) |
| `error_message` | TEXT | YES | populated on `error` / `dead_letter` outcomes; truncated to 500 chars |
| `duration_ms` | INTEGER | YES | handler wall-clock ms |
| `attempted_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |

**Indexes:**
- `idx_dispatcher_event_attempts_event_id` on `(event_id)` — drives the polling exclusion sub-query
- `idx_dispatcher_event_attempts_attempted_at` on `(attempted_at DESC)` — drives metrics aggregations (last hour, last 24h)
- `idx_dispatcher_event_attempts_outcome_recent` partial on `(attempted_at DESC) WHERE outcome IN ('error', 'dead_letter')` — drives operator alerting

**Metrics derived from this table** (no separate metrics table needed):

| metric | aggregation |
|---|---|
| `processed_last_hour` | `COUNT(*) WHERE outcome='success' AND attempted_at >= NOW() - '1 hour'` |
| `failed_last_hour` | `COUNT(*) WHERE outcome='error' AND attempted_at >= NOW() - '1 hour'` |
| `dead_lettered_last_hour` | `COUNT(*) WHERE outcome='dead_letter' AND attempted_at >= NOW() - '1 hour'` |
| `mean_handler_ms` | `AVG(duration_ms) WHERE outcome='success' AND attempted_at >= NOW() - '1 hour'` |
| `p99_handler_ms` | `PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) WHERE outcome='success'` |

### 5.4 Dead-letter pattern

Once `attempt_number >= max_retries` for an event, the next dispatcher cycle:

- Inserts a final `legal.dispatcher_event_attempts` row with `outcome='dead_letter'`
- Sets `legal.event_log.processed_at = NOW()` (event leaves the polling queue)
- Sets `legal.event_log.processed_by = 'legal_dispatcher:dead_letter'`
- Sets `legal.event_log.result = {"status": "dead_letter", "final_error": "...", "attempts": N}`
- Emits a fresh `dispatcher.dead_letter` event (re-enters `event_log`; observable via the operator surface)

The `dispatcher.dead_letter` handler (§6.7) is observability-only — appends to `legal.dispatcher_dead_letter` (the long-term retained log) and emits no further events.

### 5.5 Worker registration

`backend/core/worker.py` — register `run_legal_dispatcher_loop` as an arq job, gated on `LEGAL_DISPATCHER_ENABLED` (default OFF), mirroring the `legal_mail_ingester` registration block. Phase 1-2 lands code inert; Phase 1-5 is the explicit flag flip.

---

## 6. Initial event handlers (Phase 1 minimum)

Phase 1 implements 4 live handlers + 2 disabled placeholders + the dead-letter sink. Each handler is responsible for:

1. Reading the event payload
2. Loading the relevant `case_posture` row (or creating it if absent)
3. Computing the new state
4. Bilateral write to `case_posture` with `updated_by_event = event.id`
5. Recomputing `posture_hash`
6. Optionally emitting downstream events

### 6.1 `email.received` (LIVE, Phase 1-3) — SCOPED v1.1

Triggered by `legal_mail_ingester:v1` on every inbound legal email.

**v1.1 scope (LOCKED):**
- Load `case_posture` for `event.case_slug` (or skip if `case_slug` is null / does not match an active case — record `result.status = 'skipped_no_case'`)
- If `event.event_payload.watchdog_matches` is non-empty, emit one `watchdog.matched` event per match
- Update `case_posture.updated_by_event = event.id` and `case_posture.updated_at = NOW()`
- Recompute `posture_hash`
- Bilateral write

**Removed from v1.1 (deferred to Phase 2+):**
- `procedural_phase` mutation logic. v1's "if email pattern indicates phase advancement" was operator-defined rules without an operator-defined ruleset — fuzzy by definition. Phase 2+ adds an operator-managed `legal.procedural_phase_rules` table and a separate handler that consumes it.

The Phase 1 `email.received` handler is intentionally narrow: it materializes case_posture rows for active cases on first observation, bumps the audit timestamps, and re-emits watchdog events for downstream handling. That is enough to validate the event→state→audit chain in Phase 1-6 24h soak without requiring a procedural_phase ruleset.

### 6.2 `watchdog.matched` (LIVE, Phase 1-3) — REVISED v1.1

Triggered by Phase 1's own `email.received` handler (re-emission) when a watchdog rule matches.

**v1.1 representation (LOCKED): `top_risk_factors` is a dict keyed by `rule_id`, not a capped list.**

```jsonb
{
  "wd-stuart-sender": {
    "rule_id": "wd-stuart-sender",
    "rule_name": "Stuart sender escalation",
    "severity": "P1",
    "first_match_at": "2026-04-15T09:12:33Z",
    "last_match_at": "2026-04-27T14:30:01Z",
    "match_count": 7
  },
  "wd-discovery-deadline": {
    "rule_id": "wd-discovery-deadline",
    "rule_name": "Discovery deadline approaching",
    "severity": "P2",
    "first_match_at": "2026-04-20T11:00:00Z",
    "last_match_at": "2026-04-26T08:45:12Z",
    "match_count": 3
  }
}
```

Logic:
- Load `case_posture` for `event.case_slug`
- Look up `event.event_payload.rule_id` in `top_risk_factors`
  - If absent: insert new entry with `first_match_at = last_match_at = NOW()`, `match_count = 1`
  - If present: increment `match_count`, update `last_match_at = NOW()`
- If severity = `P1`, emit `operator.alert` event (manual queue — handler stub for Phase 1; full alert routing in Phase 2+)
- Update `updated_by_event`, `updated_at`, recompute `posture_hash`, bilateral write

**Why the change:** v1's "append match capped at 50" produced 50 instances of "Stuart sent email again" — operationally noise. v1.1's per-rule aggregation gives one entry per rule with frequency + recency, naturally bounded by the count of active watchdog rules (~10-30 per case). Operator dashboards surface "rule X matched 7 times, last 5 minutes ago" — actionable signal.

### 6.3 `operator.input` (LIVE, Phase 1-3)

Triggered by future operator CLI commands (`fgp legal posture set ...` — Phase 2+ scope, but the route is wired in Phase 1).

Logic:
- Validate payload (`{ "command": "...", "fields": {...} }`)
- Apply field mutations directly to `case_posture` (operator override)
- Always cites `updated_by_event = event.id` so the audit trail records "operator made this change"

For Phase 1 we wire the route + handler skeleton; operator-input events emitted in Phase 1 are test fixtures during 1-3 development. Live operator commands are Phase 2+.

### 6.4 `vault.document_ingested` (PLACEHOLDER, `enabled=FALSE`)

Phase 0a's Vault ingester does NOT yet emit this event. Route seeded `enabled=FALSE`. Handler stub returns `{"status": "placeholder_not_implemented"}`. Activates when the Vault ingester is brought into FLOS (Phase 2+ candidate).

### 6.5 `council.deliberation_complete` (PLACEHOLDER, `enabled=FALSE`)

Same posture as 6.4. Council currently writes its own audit rows; FLOS-design-v1 §3.5 calls for migration to `event_log`. That migration is Phase 2+ work.

### 6.6 `dispatcher.dead_letter` (LIVE, Phase 1-3)

Self-emission for events that exhausted retries. Handler is observability-only — appends to `legal.dispatcher_dead_letter` (the long-term retained log) and surfaces via CLI + health endpoint.

`legal.dispatcher_dead_letter` schema (LOCKED):

| field | type | nullable | notes |
|---|---|---|---|
| `id` | BIGSERIAL | NO | PK |
| `original_event_id` | BIGINT | NO | FK to `legal.event_log.id` |
| `event_type` | TEXT | NO | denormalized from event_log for query convenience |
| `case_slug` | TEXT | YES | denormalized |
| `final_error` | TEXT | NO | from last attempt's error_message |
| `attempts` | INTEGER | NO | total attempt count |
| `dead_lettered_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |

Retention: operator-triggered purge only (Q3 LOCKED). See `fgp legal dispatcher dead-letter purge` (§8.1).

---

## 7. Event bus mechanism — closing FLOS v1 Q4

FLOS-design-v1 left this open: Postgres LISTEN/NOTIFY vs Redis pub/sub.

**Recommendation: Postgres LISTEN/NOTIFY for v1.**

Rationale:
- Zero new infrastructure — Postgres is already the canonical store; `event_log` already lives there
- Same DB transaction discipline — emitter's `INSERT INTO event_log` and the NOTIFY can be in the same transaction, so notification is exactly synchronized with the row's visibility
- Latency is in the millisecond range — far below the dispatcher's batch-poll cadence
- Decommissioning the queue means dropping a pg LISTEN — no Redis migration to plan

**When to migrate to Redis pub/sub:**
- Multiple dispatcher workers across sparks need fan-out
- Event volume exceeds ~1k/sec sustained
- Event consumers outside the legal stack need to subscribe

**Critical:** the dispatcher does **not** strictly require LISTEN/NOTIFY. The polling loop on `idx_event_log_unprocessed` (Phase 0a-1) is sufficient on its own — events are picked up on the next poll cycle. LISTEN/NOTIFY is a wake-up signal that lets the dispatcher react in <100ms instead of waiting for the next 5s poll. **Phase 1-2 ships polling-only.** LISTEN/NOTIFY is added as a Phase 1-2b optimization if dispatcher lag matters in the 24h soak.

---

## 8. Operator surface

### 8.1 CLI — `backend/scripts/legal_dispatcher_cli.py`

Mirrors `legal_mail_ingester_cli.py`'s structure (argparse, plan-by-default for mutators):

```
fgp legal dispatcher status
    Reads dispatcher_routes + dispatcher_event_attempts + event_log lag.
    Surfaces:
      - routes (event_type, handler, enabled)
      - last hour: events processed / failed / dead-lettered (from
        dispatcher_event_attempts aggregations)
      - oldest unprocessed event age (queue depth signal)

fgp legal dispatcher pause / resume
    Bilateral write to legal.dispatcher_pause (single-row table — no
    per-event-type pause for v1).

fgp legal dispatcher replay --event-id N [--confirm]
    Plan-by-default: shows what would re-run.
    --confirm: clears processed_at on the event and the
    dispatcher_event_attempts rows for that event; lets the dispatcher
    pick it up on the next cycle. Useful for handler bug recovery.

fgp legal dispatcher dead-letter list [--limit 50]
    Reads legal.dispatcher_dead_letter ordered by dead_lettered_at DESC.

fgp legal dispatcher dead-letter purge --before YYYY-MM-DD --confirm
    Operator-triggered cleanup. Plan-by-default; requires --confirm.
    Deletes legal.dispatcher_dead_letter rows older than --before.
    Bilateral. Phase 1-4 scope (per Q3 LOCKED).

fgp legal posture get --case-slug X [--json]
    Reads legal.case_posture for one case.

fgp legal posture history --case-slug X [--limit 20]
    Walks event_log for the case in time order.
    (Read-only; relies on event_log.case_slug index.)
```

### 8.2 HTTP — `/api/internal/legal/dispatcher/health`

Programmatic twin. Same auth pattern as `/api/internal/legal/mail/health` (Bearer + X-Fortress-Ingress + X-Fortress-Tunnel-Signature).

Response shape (LOCKED for v1.1):

```
{
  "service": "legal_dispatcher",
  "version": "v1",
  "dispatcher_enabled": true,
  "checked_at": "...",
  "overall_status": "ok" | "degraded" | "disabled" | "lagging",
  "queue": {
    "unprocessed_total": 12,
    "oldest_unprocessed_age_sec": 4.2,
    "processed_last_hour": 145,
    "failed_last_hour": 0,
    "dead_lettered_last_hour": 0,
    "mean_handler_ms": 32,
    "p99_handler_ms": 410
  },
  "routes": [
    {"event_type": "email.received", "enabled": true, "handler": "..."}
  ],
  "summary": { ... }
}
```

`overall_status: "lagging"` is triggered when `oldest_unprocessed_age_sec > 60` (PROPOSED threshold). Distinct from `degraded` (handler errors via `failed_last_hour > 0`) and `disabled` (flag off).

### 8.3 Per-case command bridge (deferred to Phase 2)

Phase 1 adds the **data** (`case_posture` row + queryable history); Phase 2 adds the **UI** (Next.js page in `apps/command-center`). Phase 1's CLI + HTTP surface are sufficient for operator workflow until the dashboard ships.

---

## 9. Source attribution + bilateral mirror

### 9.1 ADR-001 bilateral discipline

Same pattern as `email_archive` and `legal.event_log` from Phase 0a:
- Canonical write: `fortress_db.legal.case_posture`
- Mirror write: `fortress_prod.legal.case_posture` (forced matching `case_slug`)
- Forward-only — never delete, never schema-drift between mirrors

The dispatcher reuses `LegacySession` and `ProdSession` from `legal_mail_ingester.py` (already exported, already proven in Phase 0a-2). No new session factories.

### 9.2 Source attribution

Every `case_posture` write records `updated_by_event = event_log.id`. The reverse: `event_log.processed_by = 'legal_dispatcher:v1'` (matches the existing CHECK regex on `event_log.emitted_by`, format `<service>:<version>`).

Audit chain:
```
legal_mail_ingester:v1   →  emits email.received row with id=N
                              ↓
legal_dispatcher:v1      →  reads event N, calls handler X
                              ↓
                              writes case_posture (case_slug=Y, updated_by_event=N)
                              writes event_log row N (processed_at=NOW(), processed_by=...)
                              writes dispatcher_event_attempts row (event_id=N, outcome=success)
```

Any mutation to `case_posture` is traceable back to the event that caused it, the producer service that emitted it, AND the dispatcher attempt that processed it.

### 9.3 Replay capability

Because every state mutation cites `updated_by_event`:
- Truncate `case_posture`
- Reset `event_log.processed_at = NULL` for rows of interest
- Truncate the corresponding `dispatcher_event_attempts` rows
- Restart dispatcher
- Current state is reconstructed deterministically — provided handlers are idempotent (Principle 6)

PROPOSED as a recovery operation, not routine workflow. Phase 1-3 must explicitly verify handler idempotency for each handler.

---

## 10. Failure modes + reliability (revised v1.1 — single retry/metrics table)

| failure | mitigation |
|---|---|
| Event handler exception | Recorded in `legal.dispatcher_event_attempts` as `outcome='error'`; retry on next poll cycle until `attempt_number = max_retries`, then dead-letter |
| `case_posture` bilateral write — primary OK, mirror fails | Logged warning; primary write counts as success; mirror retried via separate operator-triggered repair pass (PROPOSED — Phase 1-6 add-on, NOT a separate metrics table) |
| `case_posture` bilateral write — primary fails | Handler raises; recorded as `outcome='error'` in dispatcher_event_attempts; retry counter increments; dispatcher continues to next event |
| Dispatcher worker crash | arq restarts the job; polling resumes from `idx_event_log_unprocessed` (no events lost — `event_log` is canonical truth) |
| `event_log` corruption | Out of scope — would require `fortress_db` recovery; Phase 0a-1's bilateral mirror is the first line of defense |
| Handler module missing/import error | Caught, recorded as `outcome='error'` with import-error message, retried like any other failure; dispatcher logs and continues |
| Schema drift between fortress_db and fortress_prod `case_posture` | Forward-only mirror discipline + operator drift-check in Phase 1-6 24h soak |

**No-event-lost guarantee:** `event_log` is append-only with `processed_at` as the only mutable column. A dispatcher crash mid-handler leaves `processed_at = NULL` (and may leave a half-written `dispatcher_event_attempts` row); the next polling cycle picks it up, and idempotent handlers absorb the re-entry safely. Removed in v1.1: any reference to a separate `legal_dispatcher_metrics` table — metrics are aggregations against `dispatcher_event_attempts`.

---

## 11. Sequencing within Phase 1

| sub-phase | scope | gates |
|---|---|---|
| 1-1 | Schema migration — `case_posture` + `dispatcher_routes` + `dispatcher_event_attempts` + `dispatcher_dead_letter` + `dispatcher_pause` tables. Bilateral application. Initial seed rows for `dispatcher_routes`. | Phase 0a fully merged + 24h soak validates |
| 1-2 | Dispatcher worker skeleton — `legal_dispatcher.py` with polling loop + `dispatcher_event_attempts` recording + empty `_HANDLERS = {}` dict (Q5 Option B). Default OFF. arq registration. NO live handlers yet. | 1-1 merged |
| 1-3 | Initial event handlers — `email.received` (scoped per §6.1), `watchdog.matched` (per-rule aggregation per §6.2), `operator.input`, `dispatcher.dead_letter`. Placeholders for `vault.document_ingested` + `council.deliberation_complete` (`enabled=FALSE`). | 1-2 merged |
| 1-4 | CLI (`legal_dispatcher_cli.py`) + health endpoint (`legal_dispatcher_health.py`). `fgp legal posture get/history` read commands. `fgp legal dispatcher dead-letter purge --before --confirm` per Q3. | 1-3 merged |
| 1-5 | Cutover — operator runs validation gate, flips `LEGAL_DISPATCHER_ENABLED=true`, restarts arq worker. | 1-4 merged + operator authorization |
| 1-6 | 24h soak — validates dispatcher lag stays bounded, no false-positive dead-letters, `case_posture` rows update for active cases, bilateral parity holds, `top_risk_factors` aggregation matches expectations. | 1-5 cutover |

Each sub-phase is one PR (mirroring Phase 0a's discipline). Sub-phase commits within a PR follow the per-commit-per-step pattern.

**Default-OFF rollout:** Phase 1-2 + 1-3 + 1-4 land code WITHOUT the worker running. `LEGAL_DISPATCHER_ENABLED=false` until 1-5. The HTTP endpoint returns `overall_status: "disabled"` during this window.

---

## 12. Open questions for operator

### Q1 — `procedural_phase` enum members [LOCKED v1.1]

**Decision:** FLOS-design-v1 defaults locked for Phase 1:
```
pre-suit, answer-due, discovery, motion, trial-prep, settlement, post-trial, closed
```

Schema CHECK constraint in Phase 1-1 migration enforces this enum exactly. Sub-phasing of `discovery` (production / depositions) and terminal-state refinements (dismissed-with-prejudice / settled-confidential) are deferred — operator can ALTER the CHECK list in a Phase 2+ migration when the operational need is concrete. Phase 1 default is `pre-suit` for new rows.

### Q2 — Dispatcher batch size per poll [LOCKED v1.1]

**Decision:** `BATCH_SIZE = 50`. Mirrors `legal_mail_ingester`'s `max_messages_per_patrol`. Phase 1-6 24h soak metrics from `dispatcher_event_attempts` (`mean_handler_ms`, `p99_handler_ms`, queue depth) inform any tuning in Phase 2.

### Q3 — Dead-letter retention policy [LOCKED v1.1]

**Decision:** Operator-triggered purge only. No automatic cleanup. New CLI command added to Phase 1-4 scope:

```
fgp legal dispatcher dead-letter purge --before YYYY-MM-DD --confirm
```

Plan-by-default; requires `--confirm`. Bilateral delete from `legal.dispatcher_dead_letter` for rows where `dead_lettered_at < :before_date`. Forces deliberate operator review; matches the bilateral-mirror "no automatic deletion" discipline. Surface lists outstanding dead-letters via `fgp legal dispatcher dead-letter list`.

### Q4 — `case_posture` versioning [LOCKED v1.1]

**Decision:** Single row per case + `event_log` audit (Option A).

`case_posture` has one row per `case_slug`; mutations overwrite. Audit history reconstructs by walking `event_log` in time order, where `updated_by_event` cites the source event. Matches existing `email_archive` pattern.

If discovery requirements later demand cleaner historical queries (attorney-work-product audit, "what did the case look like on date X"), upgrade path is a Phase 2+ migration to versioned rows. The schema evolution is straightforward (drop PK on `case_slug`, add `version_id BIGSERIAL` PK, add `(case_slug, updated_at DESC)` index, add a `current` view) — not gating.

### Q5 — Handler module layout [CLOSED v1.1]

**Decision: Option B — single file.**

`backend/services/legal_dispatcher.py` contains a module-level `_HANDLERS = {"email.received": _handle_email_received, ...}` dict mapping event_type → handler callable. `dispatcher_routes.handler_function` is the dict key; `dispatcher_routes.handler_module` defaults to a sentinel (e.g. the dispatcher module path itself, used only for `event_log.processed_by` formatting).

Rationale:
- Matches `legal_mail_ingester.py`'s in-file `classify_inbound` pattern (single source of truth for one service's behavior)
- 4 live handlers fit comfortably in one file without ownership-boundary friction
- One file to grep, one file to test, one place handlers can share private helpers without import gymnastics

Phase 2+ migration trigger: when handler count grows beyond ~8–10, or when per-handler test isolation requires its own module. The migration is a routine refactor — split each handler into its own module under `backend/services/legal_dispatcher_handlers/`, update `_HANDLERS` dict, update `dispatcher_routes.handler_module` rows. Schema unchanged; no breaking-change ALTER required.

---

## 13. Architectural principles (LOCKED across v1 and v1.1)

### Principle 1 — Events drive state. Always.

`legal.case_posture` is mutated **only** by the dispatcher consuming `legal.event_log`. No other code path writes to `case_posture`. No HTTP endpoint, no service, no CLI shortcut bypasses the dispatcher.

This is the load-bearing invariant of FLOS Phase 1. It is what makes audit replay possible (§9.3) and what gives every `case_posture` cell a traceable provenance back to the event that caused it.

Implications:
- Operator manual mutations go through `operator.input` events, not direct SQL
- "Quick fixes" via psql update are an audit violation; the correct path is to emit a corrective `operator.input` event
- The dispatcher is the single writer; if it is paused, `case_posture` is frozen — that is the correct behavior

LOCKED. Future ADR-006 (FLOS Phase 1) will codify it.

### Principle 2 — Default OFF (LOCKED across all Phase 1 sub-phases)

Code lands inert. `LEGAL_DISPATCHER_ENABLED=false` default. Cutover is operator-explicit; no auto-activation.

### Principle 3 — Bilateral mirror discipline (LOCKED, ADR-001)

`case_posture` writes hit fortress_db + fortress_prod. Forward-only. Same pattern as `email_archive` and `event_log`.

### Principle 4 — Source attribution (LOCKED)

Every `case_posture` mutation cites `updated_by_event` (FK to `event_log.id`). The reverse: every `event_log.processed_by` matches `^[a-z_]+:[a-z0-9_.-]+$` (already enforced by Phase 0a-1's CHECK).

### Principle 5 — Operator-explicit cutover and pause (LOCKED, mirrors Phase 0a)

Phase 1-5 cutover is a separate authorization. Pause/resume operates per-dispatcher (not per-route in v1). Sticky pause survives worker restart.

### Principle 6 — Idempotent handlers (LOCKED)

Every handler must produce the same `case_posture` state for the same input event sequence regardless of when it runs. Verified by Phase 1-3 review; reinforced by Phase 1-6 24h soak.

### Principle 7 — Single retry/metrics table (LOCKED v1.1, NEW)

`legal.dispatcher_event_attempts` is the single source of truth for retry tracking AND metrics. No parallel `legal_dispatcher_metrics` table; no separate observability schema. Metrics derive from aggregations against the attempts table. This avoids double-write divergence and keeps the failure-mode story single-tabled.

---

## 14. Cross-references

- Parent: `FLOS-design-v1.md` §3.1 (state store), §3.2 (event bus), §3.3 (action dispatcher), §3.4 (operator surface), §3.5 (audit trail)
- Predecessor: `FLOS-phase-1-state-store-design.md` (v1, preserved as review history)
- Phase 0a-1: `q2b3c4d5e6f7_flos_phase_0a_1_legal_mail_ingester_schema.py` — `event_log` table + `idx_event_log_unprocessed` partial index this dispatcher polls
- Phase 0a-2: `backend/services/legal_mail_ingester.py` — producer; exports `LegacySession`, `ProdSession`, `INGESTER_VERSIONED` reused by the dispatcher
- Phase 0a-3: `backend/scripts/legal_mail_ingester_cli.py` + `backend/api/legal_mail_health.py` — CLI + health-endpoint patterns mirrored here
- ADR-001 — one-spark-per-division
- ADR-002 — Captain + Sentinel on Spark 2 permanent (legal_dispatcher co-located here for Phase 1)
- ADR-003 — inference plane (legal_dispatcher does NOT run inference)
- Future ADR-006 (PROPOSED) — FLOS Phase 1 LOCKED design

---

## 15. Status flag (v1.1)

| element | status |
|---|---|
| `legal.case_posture` schema (§3) | **LOCKED** — 18 fields; Phase 1 populates a subset (annotated) |
| `legal.dispatcher_routes` schema (§4) | **LOCKED** — `priority` removed in v1.1; 6 seed rules (4 enabled, 2 placeholder-disabled) |
| `legal.dispatcher_event_attempts` schema (§5.3) | **LOCKED** — single retry/metrics table |
| `legal.dispatcher_dead_letter` schema (§6.6) | **LOCKED** — operator-triggered retention |
| Dispatcher worker mechanics (§5) | **LOCKED** — polling-only ships in 1-2; LISTEN/NOTIFY deferred to 1-2b |
| Handler scope (§6) | **LOCKED** — `email.received` scoped to load+watchdog-emit only; `watchdog.matched` aggregates per `rule_id` |
| Event bus mechanism (§7) | **LOCKED — Postgres LISTEN/NOTIFY** (deferred to 1-2b optimization) |
| Operator surface (§8) | **LOCKED** — CLI + HTTP shapes; `dead-letter purge` added to 1-4 scope |
| Bilateral mirror (§9) | **LOCKED** by ADR-001 |
| Failure modes (§10) | **LOCKED** — single retry/metrics table; no separate metrics schema |
| Sub-phase sequencing (§11) | **LOCKED** — six sub-phases 1-1 → 1-6 |
| Q1 procedural_phase enum (§12) | **CLOSED** — FLOS-design-v1 defaults |
| Q2 batch size (§12) | **CLOSED** — 50 |
| Q3 dead-letter retention (§12) | **CLOSED** — operator-triggered purge |
| Q4 versioning (§12) | **CLOSED** — single row + event_log audit |
| Q5 handler module layout (§12) | **CLOSED** — Option B (single file with `_HANDLERS` dict in `legal_dispatcher.py`) |
| Principles 1–7 (§13) | **LOCKED** (Principle 7 new in v1.1) |

**Document fully LOCKED.** No further revisions. Phase 1-1 schema migration authorization is the next operator move.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
