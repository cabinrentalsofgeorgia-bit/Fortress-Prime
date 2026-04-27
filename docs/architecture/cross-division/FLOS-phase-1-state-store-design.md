# FLOS Phase 1 — State Store + Event Dispatcher

**Status:** PROPOSED — operator review pending
**Author:** assistant (with operator)
**Date:** 2026-04-27
**Parent:** `FLOS-design-v1.md` §3.1 (state store), §3.2 (event bus), §3.3 (action dispatcher), §3.5 (audit trail)
**Stacks on:** Phase 0a-1 (PR #245), Phase 0a-2 (PR #246), Phase 0a-3 (PR #247)
**Sequencing:** Phase 1 follows Phase 0a end-to-end merge + Phase 0a-5 24h soak

---

## 1. Goals

Phase 0a established the **producer side** of FLOS: the `legal_mail_ingester` writes `email.received` events to `legal.event_log`. Events accumulate but no consumer reads them; the queue grows monotonically.

Phase 1 establishes the **consumer side**:

1. **State store (`legal.case_posture`)** — one row per active matter. Structured fields cover procedural phase, deadlines, exposure, leverage, theory of defense, and the most recent Council consensus. Replaces ad-hoc reconstruction (briefing-pack PDF + correspondence dir + email_archive query) with a single canonical row.
2. **Action dispatcher (`backend/services/legal_dispatcher.py`)** — a worker that polls `legal.event_log WHERE processed_at IS NULL`, dispatches each event through a config-driven routing table (`legal.dispatcher_routes`), and projects state mutations into `legal.case_posture`. Updates `event_log.processed_at + processed_by + result` on completion.
3. **Operator surface** — read-only access to `case_posture` via CLI (`fgp legal posture get --case-slug X`) and HTTP health endpoint (`/api/internal/legal/dispatcher/health`).

The dispatcher is the **only writer** to `case_posture`. Other code paths read; they do not mutate. This is the load-bearing invariant of Phase 1 (see §13 Principle 1).

`legal.event_log` already exists (Phase 0a-1, migration `q2b3c4d5e6f7`). Phase 1 adds the consumer; the producer was Phase 0a.

---

## 2. Architectural placement

### 2.1 Spark allocation (per ADR-002)

| component | spark | rationale |
|---|---|---|
| `legal_mail_ingester` (producer) | Spark 2 | LOCKED — email IMAP polling, control-plane class |
| `legal_dispatcher` (consumer) | Spark 2 | PROPOSED — control-plane consumer; co-located with producer; same `fortress-arq-worker` runtime |
| `legal.case_posture` table | fortress_db (Spark 1, primary) + fortress_prod (Spark 1, mirror) | LOCKED — bilateral discipline, ADR-001 |
| Future Council deliberation triggered by dispatcher | Spark 4 | ADR-002 LOCKED — Council always Spark 4 |
| Future legal-NIM brain inference | Spark 1 | ADR-003 — inference plane |

The dispatcher itself is small (Postgres polling + JSON dispatch). It does not run inference. Spark 2 co-location with `legal_mail_ingester` keeps the writer→consumer hop in-process latency terms (no inter-spark round trip).

### 2.2 File placement

| file | role |
|---|---|
| `backend/services/legal_dispatcher.py` | dispatcher worker — patrol loop, event handler dispatch, state mutation |
| `backend/services/legal_dispatcher_handlers/` (package) | one module per event-type handler (PROPOSED — operator may prefer single-file) |
| `backend/scripts/legal_dispatcher_cli.py` | operator CLI: `status`, `pause`, `resume`, `replay`, `posture get` |
| `backend/api/legal_dispatcher_health.py` | HTTP health endpoint at `/api/internal/legal/dispatcher/health` |
| `backend/alembic/versions/<rev>_flos_phase_1_1_case_posture_schema.py` | schema migration (Phase 1-1) |

The package layout for handlers is PROPOSED — operator may prefer a single dispatcher file with a `_HANDLERS` dict of callables, mirroring how `classify_inbound` lives inside `legal_mail_ingester.py`. Decision belongs to operator before Phase 1-2.

---

## 3. `legal.case_posture` schema (PROPOSED)

One row per active matter, identified by `case_slug` (FK to `legal.cases.slug`).

Conceptual fields per FLOS-design-v1 §3.1:

| field | type | nullable | notes |
|---|---|---|---|
| `case_slug` | TEXT | NO | PRIMARY KEY; FK to `legal.cases.slug` |
| `procedural_phase` | TEXT | NO | enum-like; CHECK constraint per Q1 below |
| `next_deadline_date` | DATE | YES | computed from `legal.case_deadlines` join |
| `next_deadline_action` | TEXT | YES | human-readable action description |
| `theory_of_defense_state` | TEXT | NO | enum: `drafting` \| `validated` \| `locked` |
| `top_defense_arguments` | JSONB | NO | structured list with evidence_element refs; default `[]` |
| `top_risk_factors` | JSONB | NO | structured list; default `[]` |
| `exposure_low` | NUMERIC(12,2) | YES | dollars |
| `exposure_mid` | NUMERIC(12,2) | YES | dollars |
| `exposure_high` | NUMERIC(12,2) | YES | dollars |
| `leverage_score` | NUMERIC(4,2) | YES | -1.00 to 1.00 |
| `opposing_counsel_profile` | JSONB | YES | name, firm, win_rate, playbook |
| `last_council_consensus` | JSONB | YES | signal, score, conviction |
| `last_council_at` | TIMESTAMPTZ | YES | when Council last deliberated this case |
| `posture_hash` | TEXT | NO | SHA-256 of canonicalized state for drift detection |
| `created_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |
| `updated_by_event` | BIGINT | YES | FK to `legal.event_log.id` — the event that caused the most recent mutation |
| `created_by_event` | BIGINT | YES | FK to `legal.event_log.id` |

**Indexes:** PK on `case_slug`; partial index on `(next_deadline_date) WHERE next_deadline_date IS NOT NULL` for "what's due in the next N days" queries.

**Constraints:**
- CHECK on `procedural_phase` (operator decides enum members — see Q1)
- CHECK on `theory_of_defense_state IN ('drafting', 'validated', 'locked')`
- CHECK on `leverage_score BETWEEN -1.00 AND 1.00`
- FK on `updated_by_event` and `created_by_event` to `legal.event_log(id)` (NOT NULL on UPDATE — every mutation must cite the source event)

**Bilateral mirror discipline (ADR-001):** every `case_posture` write hits both `fortress_db` (canonical) and `fortress_prod` (mirror), with forced matching `case_slug`. Forward-only — no schema drift between the two.

**Versioning question:** Q4 below — single row vs versioned history.

---

## 4. `legal.dispatcher_routes` schema (PROPOSED)

Config-driven event-type → handler mapping. Lets the operator iterate routing rules without code changes.

| field | type | nullable | notes |
|---|---|---|---|
| `event_type` | TEXT | NO | PRIMARY KEY; matches `event_log.event_type` |
| `handler_module` | TEXT | NO | dotted path, e.g. `backend.services.legal_dispatcher_handlers.email_received` |
| `handler_function` | TEXT | NO | callable name within the module |
| `enabled` | BOOLEAN | NO | DEFAULT TRUE; allows disabling a route without deletion |
| `priority` | INTEGER | NO | DEFAULT 100; lower number = earlier dispatch when multiple events ready |
| `max_retries` | INTEGER | NO | DEFAULT 5 |
| `description` | TEXT | YES | human-readable purpose |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | |

**Initial seed rules** (Phase 1-1 migration):

| event_type | handler |
|---|---|
| `email.received` | `legal_dispatcher_handlers.email_received.handle` |
| `vault.document_ingested` | `legal_dispatcher_handlers.vault_document_ingested.handle` (placeholder — Vault ingester emission is future work) |
| `watchdog.matched` | `legal_dispatcher_handlers.watchdog_matched.handle` |
| `council.deliberation_complete` | `legal_dispatcher_handlers.council_deliberation_complete.handle` (placeholder) |
| `operator.input` | `legal_dispatcher_handlers.operator_input.handle` |

Routes for `email.received` are wired live in Phase 1; placeholder routes for `vault.document_ingested` and `council.deliberation_complete` are seeded with `enabled=FALSE` so the dispatcher does not error when those event types are emitted before handlers exist.

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

**Polling SQL** (uses Phase 0a-1's `idx_event_log_unprocessed` partial index):

```
SELECT id, event_type, case_slug, event_payload, emitted_at, emitted_by
FROM legal.event_log
WHERE processed_at IS NULL
ORDER BY emitted_at
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

`FOR UPDATE SKIP LOCKED` permits horizontal scaling later (multiple dispatcher workers) without double-processing. PROPOSED — single-worker is sufficient for Phase 1; the lock hint costs nothing now and de-risks Phase 2 scale-out.

### 5.2 Per-event dispatch

```
async def dispatch_event(event):
    route = get_route(event.event_type)              # legal.dispatcher_routes lookup
    if route is None or not route.enabled:
        await mark_skipped(event.id, reason="no_route" | "route_disabled")
        return
    handler = import_handler(route.handler_module, route.handler_function)
    try:
        result = await handler(event)
        await mark_processed(event.id, processed_by=route.handler_module + ":" + route.handler_function, result=result)
    except Exception as exc:
        await record_retry(event.id, exc, max_retries=route.max_retries)
```

### 5.3 Failure handling — retry + dead-letter

Retry counter lives on a sibling table `legal.dispatcher_event_attempts` (PROPOSED) keyed `(event_id, attempt_number)`. Each failure records the attempt; the dispatcher's polling SQL excludes events with `attempts >= max_retries`. Once the threshold is reached:

- `event_log.processed_at` is set (event is no longer "pending" from polling's view)
- `event_log.processed_by = 'legal_dispatcher:dead_letter'`
- `event_log.result = {"status": "dead_letter", "final_error": "..."}` 
- A `dispatcher.dead_letter` event is emitted (re-enters event_log; observable via `fgp legal mail status` analog)

Dead-letter events surface in the operator CLI and health endpoint — not silently buried.

### 5.4 Worker registration

`backend/core/worker.py` — register `run_legal_dispatcher_loop` as an arq job, gated on `LEGAL_DISPATCHER_ENABLED` (default OFF), mirroring the `legal_mail_ingester` registration block. Default OFF means Phase 1-2's code lands inert; Phase 1-5 cutover is the explicit flag flip.

---

## 6. Initial event handlers (Phase 1 minimum)

Phase 1 implements 4 live handlers + 2 placeholders. Each handler is responsible for:

1. Reading the event payload
2. Loading the relevant `case_posture` row (or creating it if absent)
3. Computing the new state
4. Bilateral write to `case_posture` with `updated_by_event = event.id`
5. Recomputing `posture_hash` (canonicalize → SHA-256)
6. Optionally emitting downstream events (e.g. `posture.changed`)

### 6.1 `email.received` (LIVE, Phase 1-3)

Triggered by `legal_mail_ingester:v1` on every inbound legal email.

Logic:
- If `event.case_slug` is null or doesn't match an active case → no-op (record `result.status = 'skipped_no_case'`)
- Else: load `case_posture` for `case_slug`
  - Update `procedural_phase` if the email pattern indicates a phase advancement (operator-defined rules; placeholder uses sender pattern: `court.gov` → still in current phase; `opposing-counsel-domain` → may advance; details in handler implementation)
  - If `event.event_payload.watchdog_matches` is non-empty, emit `watchdog.matched` events (one per match)
  - Refresh `last_council_consensus` is NOT done here (only `council.deliberation_complete` does that)
- Bilateral write `case_posture` with new `updated_by_event = event.id`

### 6.2 `watchdog.matched` (LIVE, Phase 1-3)

Triggered by Phase 1's own `email.received` handler (re-emission) when a watchdog rule matches.

Logic:
- Load `case_posture` for `event.case_slug`
- Append the watchdog match to `top_risk_factors` JSONB (capped at last 50 entries)
- If watchdog severity = `P1`, emit `operator.alert` event (manual queue)

This handler is the seed of Layer 1 of FLOS — "events trigger structured state changes that the operator can act on."

### 6.3 `operator.input` (LIVE, Phase 1-3)

Triggered by the operator CLI (`fgp legal posture set ...` — out of Phase 1 scope, but the event type is wired so future commands route correctly).

Logic:
- Validate payload (`{ "command": "...", "fields": {...} }`)
- Apply field mutations directly to `case_posture` (operator override)
- Always cites `updated_by_event = event.id` so the audit trail records "operator made this change"

For Phase 1 we wire the route; the only `operator.input` events emitted in Phase 1 are test fixtures during 1-3 development.

### 6.4 `vault.document_ingested` (PLACEHOLDER, Phase 1-3)

Phase 0a's Vault ingester does NOT yet emit this event. The route is seeded `enabled=FALSE` to prevent dispatcher errors if the event type appears prematurely. Handler stub returns `{"status": "placeholder_not_implemented"}`.

Activated when the Vault ingester is brought into FLOS (out of Phase 1 scope — Phase 2 candidate).

### 6.5 `council.deliberation_complete` (PLACEHOLDER, Phase 1-3)

Same posture as 6.4. Council currently writes its own audit rows; FLOS-design-v1 §3.5 calls for migration to `event_log`. That migration is Phase 2+ work.

### 6.6 `dispatcher.dead_letter` (LIVE, Phase 1-3)

Self-emission for failed events. Handler is observability-only — appends to a `legal.dispatcher_dead_letter` table (PROPOSED — single field log, operator surfaces via CLI).

---

## 7. Event bus mechanism — closing FLOS v1 Q4

FLOS-design-v1 left this open: Postgres LISTEN/NOTIFY vs Redis pub/sub.

**Recommendation: Postgres LISTEN/NOTIFY for v1.**

Rationale:
- Zero new infrastructure — Postgres is already the canonical store; `event_log` already lives there
- Same DB transaction discipline — emitter's `INSERT INTO event_log` and the NOTIFY can be in the same transaction, so notification is exactly synchronized with the row's visibility
- Latency is in the millisecond range — far below the dispatcher's batch-poll cadence; fast enough for any operator-visible workflow
- Decommissioning the queue means dropping a pg LISTEN — no Redis migration to plan

**When to migrate to Redis pub/sub:**
- If multiple dispatcher workers across sparks need fan-out (Postgres NOTIFY fans out to all listeners on the same DB, but cross-spark scale tests should validate)
- If event volume exceeds ~1k/sec sustained (Postgres NOTIFY's payload size limit and per-connection backlog become bottlenecks above this)
- If event consumers outside the legal stack need to subscribe (Redis is more polyglot)

For Phase 1, Postgres LISTEN/NOTIFY is **PROPOSED**. Operator may override to Redis pub/sub if scale or cross-system consumer requirements emerge before Phase 1-2 begins.

**Critical detail:** the dispatcher does **not** strictly require LISTEN/NOTIFY. The polling loop on `idx_event_log_unprocessed` (Phase 0a-1) is sufficient on its own — it will pick up events on the next poll cycle. LISTEN/NOTIFY is a **wake-up signal** that lets the dispatcher react in <100ms instead of waiting for the next poll. It is an optimization, not a correctness requirement. Phase 1-2 may ship polling-only and add LISTEN/NOTIFY as a Phase 1-2b optimization if dispatcher lag matters.

---

## 8. Operator surface

### 8.1 CLI — `backend/scripts/legal_dispatcher_cli.py`

Mirrors `legal_mail_ingester_cli.py`'s structure (5 subcommands, argparse, plan-by-default for mutators):

```
fgp legal dispatcher status
    Reads dispatcher_routes + dispatcher_event_attempts + event_log lag.
    Surfaces:
      - routes (event_type, handler, enabled, priority)
      - last hour: events processed / failed / dead-lettered
      - oldest unprocessed event age (queue depth signal)

fgp legal dispatcher pause / resume
    Bilateral write to legal.dispatcher_pause (single-row table — no
    per-event-type pause for v1; operator may iterate to per-route).

fgp legal dispatcher replay --event-id N [--confirm]
    Plan-by-default: shows what would re-run.
    --confirm: clears processed_at on the event and lets the dispatcher
    pick it up on the next cycle. Useful for handler bug recovery.

fgp legal posture get --case-slug X
    Reads legal.case_posture for one case. Emits human-readable summary
    or JSON (--json flag for tooling).

fgp legal posture history --case-slug X [--limit 20]
    Walks event_log for the case in time order. Renders the procedural
    advance over time. (Read-only; relies on event_log.case_slug index.)
```

### 8.2 HTTP — `/api/internal/legal/dispatcher/health`

Programmatic twin of `fgp legal dispatcher status`. Same auth pattern as `/api/internal/legal/mail/health` (Bearer + X-Fortress-Ingress + X-Fortress-Tunnel-Signature).

Response shape (PROPOSED):

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
    "dead_lettered_last_hour": 0
  },
  "routes": [
    {"event_type": "email.received", "enabled": true, "handler": "...", "priority": 100}
  ],
  "summary": { ... }
}
```

`overall_status: "lagging"` is a new Phase 1 status. Triggered when `oldest_unprocessed_age_sec > LAG_THRESHOLD` (PROPOSED: 60 seconds). Distinct from `degraded` (handler errors) and `disabled` (flag off).

### 8.3 Per-case command bridge (deferred to Phase 2)

FLOS-design-v1 §3.4 describes the per-case dashboard. Phase 1 adds the **data** (`case_posture` row + queryable history); Phase 2 adds the **UI** (Next.js page in `apps/command-center`). Phase 1's CLI + HTTP surface are sufficient for operator workflow until the dashboard ships.

---

## 9. Source attribution + bilateral mirror

### 9.1 ADR-001 bilateral discipline

Same pattern as `email_archive` and `legal.event_log` from Phase 0a:
- Canonical write: `fortress_db.legal.case_posture`
- Mirror write: `fortress_prod.legal.case_posture` (forced matching `case_slug`)
- Forward-only — never delete, never schema-drift between mirrors

The dispatcher reuses `LegacySession` and `ProdSession` from `legal_mail_ingester.py` (already exported, already proven in Phase 0a-2). No new session factories.

### 9.2 Source attribution

Every `case_posture` write records `updated_by_event = event_log.id`. The reverse direction is also enforced: `event_log.processed_by = 'legal_dispatcher:v1'` (matches the existing CHECK regex on `event_log.emitted_by`, format `<service>:<version>`).

This is the audit chain:
```
legal_mail_ingester:v1   →  emits email.received row with id=N
                              ↓
legal_dispatcher:v1      →  reads event N, calls handler X
                              ↓
                              writes case_posture (case_slug=Y, updated_by_event=N)
                              writes event_log row N (processed_at=NOW(), processed_by=...)
```

Any mutation to `case_posture` is traceable back to the event that caused it, which is traceable back to the producer service that emitted it.

### 9.3 Replay capability

Because every state mutation cites `updated_by_event`:
- Truncate `case_posture`
- Reset `event_log.processed_at = NULL` for all rows of interest
- Restart dispatcher
- The current state is reconstructed deterministically

This is **PROPOSED** as a recovery operation, not part of routine workflow. The deterministic-replay property comes from handler idempotency — Phase 1 handlers must be designed to produce the same `case_posture` state for the same input event sequence regardless of when they run. Phase 1-3 must explicitly verify this for each handler.

---

## 10. Failure modes + reliability

| failure | mitigation |
|---|---|
| Event handler exception | Logged + per-event retry (see §5.3); 5 retries → dead-letter |
| `case_posture` bilateral write — primary OK, mirror fails | Logged warning; primary write counts as success; mirror retried via `legal_dispatcher_metrics` repair pass (PROPOSED — Phase 1-6 add-on) |
| `case_posture` bilateral write — primary fails | Event marked failed, retry counter increments; dispatcher continues to next event |
| Dispatcher worker crash | arq restarts the job; polling resumes from `idx_event_log_unprocessed` (no events lost — `event_log` is canonical truth) |
| `event_log` corruption | Out of scope — would require `fortress_db` recovery; Phase 0a-1's bilateral mirror is the first line of defense |
| Handler module missing/import error | Route marked errored at registration; dispatcher logs and skips (does not crash); operator surfaces via `fgp legal dispatcher status` |
| Schema drift between fortress_db and fortress_prod `case_posture` | Forward-only mirror discipline + operator drift-check in Phase 1-6 24h soak |

**No-event-lost guarantee:** `event_log` is append-only with `processed_at` as the only mutable column. A dispatcher crash mid-handler leaves `processed_at = NULL`; the next polling cycle picks it up. Idempotent handlers absorb the re-entry safely.

---

## 11. Sequencing within Phase 1

| sub-phase | scope | gates |
|---|---|---|
| 1-1 | Schema migration — `case_posture` + `dispatcher_routes` + `dispatcher_event_attempts` + `dispatcher_dead_letter` + `dispatcher_pause` tables. Bilateral application (fortress_db + fortress_prod). Initial seed rows for `dispatcher_routes`. | Phase 0a fully merged + 24h soak validates (no point building consumer if producer is broken) |
| 1-2 | Dispatcher worker skeleton — `legal_dispatcher.py` with polling loop, dispatch dispatch, retry table integration. Default OFF. arq registration. NO live handlers yet. | 1-1 merged |
| 1-3 | Initial event handlers — `email.received`, `watchdog.matched`, `operator.input` LIVE. Placeholders for `vault.document_ingested` + `council.deliberation_complete`. Dead-letter handler. | 1-2 merged |
| 1-4 | CLI (`legal_dispatcher_cli.py`) + health endpoint (`legal_dispatcher_health.py`). `fgp legal posture get` read-only command. | 1-3 merged |
| 1-5 | Cutover — operator runs validation gate, flips `LEGAL_DISPATCHER_ENABLED=true`, restarts arq worker. | 1-4 merged + operator authorization |
| 1-6 | 24h soak — validates dispatcher lag stays bounded, no false-positive dead-letters, `case_posture` rows update for active cases, bilateral parity holds. | 1-5 cutover |

Each sub-phase is one PR (mirroring Phase 0a's discipline). Sub-phase commits within a PR follow the same per-commit-per-step pattern.

**Default-OFF rollout:** Phase 1-2 + 1-3 + 1-4 land code WITHOUT the worker running. `LEGAL_DISPATCHER_ENABLED=false` until 1-5. The HTTP endpoint returns `overall_status: "disabled"` during this window.

---

## 12. Open questions for operator

### Q1 — `procedural_phase` enum members

FLOS-design-v1 suggested: `pre-suit, answer-due, discovery, motion, trial-prep, settlement, post-trial, closed`.

Concerns to validate:
- Does the legal team's actual practice match this taxonomy?
- Are sub-phases needed (e.g. `discovery.production`, `discovery.depositions`)?
- Is `closed` sufficient, or are there terminal states like `dismissed-with-prejudice`, `settled-confidential`, `judgment-entered`?

**Default if not iterated:** the FLOS-design-v1 list is taken as Phase 1 PROPOSED. Operator must lock before Phase 1-1 schema migration.

### Q2 — Dispatcher batch size per poll

Polling SQL has `LIMIT :batch_size`. Larger batches = fewer round trips but longer per-poll latency.

Options:
- 10 — conservative; bounded per-cycle work; fast operator response if a slow handler appears
- 50 — middle ground; matches `legal_mail_ingester`'s `max_messages_per_patrol` default
- 100 — high throughput; appropriate if event volume rises

**Default if not iterated:** 50, mirroring `legal_mail_ingester`. Phase 1-6 24h soak metrics will inform tuning.

### Q3 — Dead-letter retention policy

Once dead-lettered, when does `legal.dispatcher_dead_letter` get cleaned up?

Options:
- Never delete (forever-retained for audit) — disk grows monotonically
- 90-day TTL — operator-triggered cleanup script
- Operator-triggered only — explicit `fgp legal dispatcher dead-letter purge --before YYYY-MM-DD --confirm`

**Default if not iterated:** Operator-triggered only. Forces deliberate review; matches the bilateral-mirror "no automatic deletion" discipline.

### Q4 — `case_posture` versioning

Two competing stances:

**A) Single row per case (PROPOSED default).** `case_posture` has one row per `case_slug`; mutations overwrite. Audit history is reconstructed by walking `event_log` in time order, where `updated_by_event` cites the source event.

**B) Versioned rows.** Each mutation appends a new row; the "current" state is the latest by `updated_at`. History is queryable directly without event_log walks.

Trade-offs:
- A: simpler queries, smaller table, audit requires event_log join
- B: every read requires a "latest" filter; storage grows with mutation rate; direct query of "what did case look like on date X" is one row lookup

**Default if not iterated:** A (single row + event_log audit). Matches existing `email_archive` pattern (no versioned mirror; audit via emit-and-event). Operator may upgrade to B if discovery requirements (e.g. attorney-work-product audit) demand cleaner historical queries.

---

## 13. Architectural principles (LOCKED in this design)

### Principle 1 — Events drive state. Always.

`legal.case_posture` is mutated **only** by the dispatcher consuming `legal.event_log`. No other code path writes to `case_posture`. No HTTP endpoint, no service, no CLI shortcut bypasses the dispatcher.

This is the load-bearing invariant of FLOS Phase 1. It is what makes audit replay possible (§9.3) and what gives every `case_posture` cell a traceable provenance back to the event that caused it.

Implications:
- Operator manual mutations go through `operator.input` events, not direct SQL
- "Quick fixes" via psql update are an audit violation; the correct path is to emit a corrective `operator.input` event
- The dispatcher is the single writer; if it is paused, `case_posture` is frozen — that is the correct behavior

This principle is **LOCKED**. Future ADR-006 (FLOS Phase 1) will codify it.

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

---

## 14. Cross-references

- Parent: `FLOS-design-v1.md` §3.1 (state store), §3.2 (event bus), §3.3 (action dispatcher), §3.4 (operator surface), §3.5 (audit trail)
- Phase 0a-1: `q2b3c4d5e6f7_flos_phase_0a_1_legal_mail_ingester_schema.py` — `event_log` table + `idx_event_log_unprocessed` partial index this dispatcher polls
- Phase 0a-2: `backend/services/legal_mail_ingester.py` — producer of `email.received` events; exports `LegacySession`, `ProdSession`, `INGESTER_VERSIONED` reused by the dispatcher
- Phase 0a-3: `backend/scripts/legal_mail_ingester_cli.py` + `backend/api/legal_mail_health.py` — CLI + health-endpoint patterns mirrored here
- ADR-001 — one-spark-per-division
- ADR-002 — Captain + Sentinel on Spark 2 permanent (legal_dispatcher co-located here for Phase 1)
- ADR-003 — inference plane (legal_dispatcher does NOT run inference; future Council-triggered handlers may invoke Spark 4)
- Future ADR-006 (PROPOSED) — FLOS Phase 1 LOCKED design

---

## 15. Status flag

| element | status |
|---|---|
| `legal.case_posture` schema (§3) | **PROPOSED** — Q1 + Q4 must close before Phase 1-1 |
| `legal.dispatcher_routes` schema (§4) | **PROPOSED** — initial seed rules subject to operator iteration |
| Dispatcher worker mechanics (§5) | **PROPOSED** — polling-only is sufficient; LISTEN/NOTIFY optimization deferrable |
| Initial handlers (§6) | **PROPOSED** for live handlers; placeholders LOCKED-disabled until producer exists |
| Event bus mechanism (§7) | **PROPOSED: Postgres LISTEN/NOTIFY** — operator may override |
| Operator surface (§8) | **PROPOSED** for CLI + HTTP shapes |
| Bilateral mirror (§9) | **LOCKED** by ADR-001 |
| Failure modes (§10) | **PROPOSED** for retry counts + dead-letter table; principle of no-event-lost is **LOCKED** |
| Sub-phase sequencing (§11) | **LOCKED** for ordering; sub-phase scope subject to operator iteration |
| Q1–Q4 (§12) | **OPEN** |
| Principles 1–6 (§13) | **LOCKED** |

Operator review next — iterate on PROPOSED items, close Q1–Q4, then this document re-issues as v1.1 LOCKED before Phase 1-1 begins.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
