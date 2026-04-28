# FLOS Phase 1-4 — Operator CLI + Health Endpoint (Implementation Spec)

**Status:** PROPOSED — operator review pending before Phase 1-4A
**Author:** assistant (with operator)
**Date:** 2026-04-27
**Parent design:** `FLOS-phase-1-state-store-design-v1.1.md` §8 (operator surface)
**Predecessor pattern:** PR #247 Phase 0a-3 (CLI + health endpoint conventions mirrored verbatim)
**Stacks on:** Phase 1-3 event handlers (PR #254) → #252 → #249 → #247 → #246 → #245
**Sequencing:** Phase 1-4 follows Phase 1-3 merge

---

## 1. Goals + scope boundary

Phase 1-4 ships the **operator surface** for `legal_dispatcher`: a CLI for direct ops invocation and an HTTP health endpoint for monitoring tools. After this PR ships, the dispatcher has both runtime and observability paths complete — Phase 1-5 cutover is the next gate.

This PR is the **validation gate before Phase 1-5 cutover.** Operator runs `fgp legal dispatcher status` + `curl /api/internal/legal/dispatcher/health` to verify configuration loaded correctly + queue is empty before flipping `LEGAL_DISPATCHER_ENABLED=true`.

**In scope:**
- CLI: `backend/scripts/legal_dispatcher_cli.py` — 7 subcommands per design v1.1 §8.1
- Health endpoint: `backend/api/legal_dispatcher_health.py` — JSON twin of CLI status
- Router registration: `backend/main.py` (+1 import + 5 lines)

**Out of scope (deferred to Phase 1-5+):**
- Cutover (operator-explicit env flip + worker restart) — Phase 1-5 separate authorization
- 24h soak validation queries — Phase 1-6
- Operator dashboard UI — Phase 2+ (Next.js page in `apps/command-center`)

**Default-OFF preserved.** CLI works against DBs regardless of flag state (read paths + bilateral writes for pause/resume/replay are flag-independent — they touch DB, not the worker process). Health endpoint returns `overall_status: "disabled"` when flag is False (distinct from `"degraded"`).

---

## 2. File structure

| file | role | new/modified |
|---|---|---|
| `backend/scripts/legal_dispatcher_cli.py` | operator CLI — argparse, 7 subcommands | NEW |
| `backend/api/legal_dispatcher_health.py` | FastAPI router — JSON health endpoint | NEW |
| `backend/main.py` | router registration mirroring `legal_mail_health` (PR #247) | MODIFIED |

No new schema (Phase 1-1 is foundation). No new service code (Phase 1-2/1-3 cover runtime). No tests (separate sub-PR per established discipline).

---

## 3. CLI module structure — `legal_dispatcher_cli.py`

Mirrors `backend/scripts/legal_mail_ingester_cli.py` (PR #247) verbatim — argparse subcommand structure, async-internal via `asyncio.run()`, direct DB access via `LegacySession` + `ProdSession` (no JWT — operator script).

### 3.1 Imports + path bootstrap

```
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_mail_ingester import ProdSession
from backend.services.legal_dispatcher import (
    DISPATCHER_VERSIONED, DEAD_LETTER_TAG, BATCH_SIZE,
    POLL_INTERVAL_SEC, MAX_ERROR_MESSAGE_LEN,
)
```

### 3.2 Output formatting helpers

Reuse the three helpers from PR #247:

| helper | purpose |
|---|---|
| `_fmt_ts(ts)` | TIMESTAMPTZ → ISO string or `(never)` |
| `_fmt_age(ts)` | TIMESTAMPTZ → human-readable age (`12s ago` / `5m ago` / `3h ago` / `2d ago`) |
| `_truncate(s, maxlen)` | error_message truncation for table display |

Inline-paste these from `legal_mail_ingester_cli.py` (NOT shared-import from a common module — Phase 0a-3 precedent kept them per-CLI).

### 3.3 Subcommands (7 total)

```
fgp legal dispatcher status                                  # §4
fgp legal dispatcher pause [--reason "..."]                  # §5
fgp legal dispatcher resume                                  # §5
fgp legal dispatcher replay --event-id N [--confirm]         # §6
fgp legal posture get --case-slug X [--json]                 # §7
fgp legal posture history --case-slug X [--limit 20]         # §8
fgp legal dispatcher dead-letter list [--limit 50]           # §9
fgp legal dispatcher dead-letter purge --before YYYY-MM-DD --confirm   # §9
```

argparse note: `dead-letter` is a sub-subparser under `dispatcher`, with `list` and `purge` as nested commands. Same pattern as Phase 0a-3 didn't use; this is a Phase 1-4 elaboration.

---

## 4. `status` subcommand

Read-only. Reads four tables, emits human-readable table.

### 4.1 Queries

```sql
-- Routes
SELECT event_type, handler_module, handler_function, enabled, max_retries
FROM legal.dispatcher_routes ORDER BY event_type;

-- Pause state
SELECT paused_at, paused_by, reason
FROM legal.dispatcher_pause WHERE singleton_id = 1 LIMIT 1;

-- Queue depth + oldest unprocessed
SELECT
    COUNT(*) AS unprocessed_total,
    EXTRACT(EPOCH FROM (NOW() - MIN(emitted_at))) AS oldest_unprocessed_age_sec
FROM legal.event_log WHERE processed_at IS NULL;

-- Last-hour aggregates
SELECT
    SUM(CASE WHEN outcome = 'success'     THEN 1 ELSE 0 END) AS processed_last_hour,
    SUM(CASE WHEN outcome = 'error'       THEN 1 ELSE 0 END) AS failed_last_hour,
    SUM(CASE WHEN outcome = 'dead_letter' THEN 1 ELSE 0 END) AS dead_lettered_last_hour,
    AVG(duration_ms)                                          AS mean_handler_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_handler_ms
FROM legal.dispatcher_event_attempts
WHERE attempted_at >= NOW() - INTERVAL '1 hour';
```

### 4.2 Output

```
legal_dispatcher (legal_dispatcher:v1) — operator status
============================================================================================
flag enabled:         false
overall:              disabled

routes (6 total, 4 live, 2 placeholder)
event_type                       handler                                      enabled  max_retries
email.received                   _handle_email_received                       true     5
watchdog.matched                 _handle_watchdog_matched                     true     5
operator.input                   _handle_operator_input                       true     5
dispatcher.dead_letter           _handle_dead_letter                          true     1
vault.document_ingested          _handle_vault_document_ingested              false    5
council.deliberation_complete    _handle_council_deliberation_complete        false    5

queue
unprocessed_total:    0
oldest_unprocessed:   (none)

last hour (from dispatcher_event_attempts)
processed:            0
failed:               0
dead_lettered:        0
mean_handler_ms:      —
p99_handler_ms:       —

pause
not paused

(dispatcher disabled at boot; CLI mutators still work; flip LEGAL_DISPATCHER_ENABLED=true to start the loop)
```

Operator-friendly summary signals at the bottom:
- "All routes loaded; queue empty; dispatcher disabled" (pre-cutover baseline)
- "N events queued; oldest is X seconds old" (active state)
- "DISPATCHER PAUSED — see paused_by / reason" (pause state)

---

## 5. `pause` and `resume` mutators

Mirrors `legal_mail_ingester pause/resume` (PR #247 Phase 0a-3) verbatim, scoped to dispatcher singleton.

### 5.1 `pause [--reason "..."]`

```sql
INSERT INTO legal.dispatcher_pause (singleton_id, paused_by, reason, paused_at)
VALUES (1, :operator, :reason, NOW())
ON CONFLICT (singleton_id) DO UPDATE
SET paused_by = EXCLUDED.paused_by,
    reason    = EXCLUDED.reason,
    paused_at = EXCLUDED.paused_at
RETURNING paused_at
```

- `paused_by` resolution: `FLOS_OPERATOR > SUDO_USER > USER > LOGNAME > getpass.getuser() > "unknown"` (matches PR #247 helper)
- Default reason: `"operator pause via CLI by <operator>"` if `--reason` not given
- Bilateral (legacy then prod mirror; mirror failure logs warning, doesn't fail command)
- Re-pause behavior: `ON CONFLICT DO UPDATE` refreshes `paused_at` + `reason` so operator can update context without `resume → pause`

Output:
```
PAUSED dispatcher
  by:     gary
  reason: investigating handler regression
  at:     just now

The dispatcher loop will skip its next cycle. To resume: fgp legal dispatcher resume
```

### 5.2 `resume`

```sql
DELETE FROM legal.dispatcher_pause WHERE singleton_id = 1
RETURNING paused_at, paused_by, reason
```

- Idempotent: `NOOP` exit 0 if no row exists
- Bilateral
- Output on success surfaces previous pause metadata for audit close-out

---

## 6. `replay` subcommand

Plan-by-default (terraform-style); `--confirm` to execute.

### 6.1 Plan mode (default — no `--confirm`)

```sql
SELECT id, event_type, case_slug, emitted_at, processed_at, processed_by
FROM legal.event_log WHERE id = :event_id;

SELECT COUNT(*) AS attempt_count,
       MAX(attempted_at) AS last_attempt_at,
       MAX(outcome) AS last_outcome
FROM legal.dispatcher_event_attempts WHERE event_id = :event_id;
```

Output:
```
REPLAY PLAN — event_id=12345
  event_type:        email.received
  case_slug:         vanderburge-v-knight-fannin
  emitted_at:        2026-04-26T14:22:00Z (1d ago)
  processed_at:      2026-04-26T14:22:03Z
  processed_by:      _handle_email_received
  attempt_count:     1
  last_outcome:      success

This will:
  - UPDATE event_log SET processed_at=NULL, processed_by=NULL, result=NULL (bilateral)
  - DELETE 1 dispatcher_event_attempts row(s) for event_id=12345 (bilateral)
  - Event re-enters polling queue on next dispatcher cycle

Pass --confirm to execute.
```

### 6.2 Execute mode (`--confirm`)

```sql
UPDATE legal.event_log
SET processed_at = NULL, processed_by = NULL, result = NULL
WHERE id = :event_id;

DELETE FROM legal.dispatcher_event_attempts WHERE event_id = :event_id;
```

Both bilateral (legacy + prod mirror).

### 6.3 Validation guards

- Event must exist (`SELECT id` returns 0 rows → exit 3 with clear error)
- Refuse if `event_log.emitted_by = 'legal_dispatcher:dead_letter'` — these are re-emitted observability events; the right replay target is the *original* event whose handler failed (its id is in the dead_letter event's payload). Output:
  ```
  ERROR: event 12345 was emitted by legal_dispatcher:dead_letter (observability re-emit).
  Replaying it doesn't undo the dead-letter; replay the original event whose handler failed.
  Original event_id is in the payload: 12340. Try: fgp legal dispatcher replay --event-id 12340 --confirm
  ```

---

## 7. `posture get` subcommand

```
fgp legal posture get --case-slug X [--json]
```

Reads `legal.case_posture` WHERE `case_slug = :slug`.

### 7.1 Output paths

**Row exists, default human-readable:**
```
case_posture for vanderburge-v-knight-fannin

procedural_phase:        pre-suit
theory_of_defense_state: drafting
top_defense_arguments:   [] (Phase 2+ population)
top_risk_factors:        2 active rules
  - wd-stuart-sender:     P1, 7 matches, last 5m ago
  - wd-discovery-deadline: P2, 3 matches, last 2h ago
exposure (low/mid/high): — / — / — (Phase 2+ population)
leverage_score:          — (Phase 2+ population)
last_council_consensus:  — (Phase 2+ population)
posture_hash:            8a3f2c9b...
created_at:              2026-04-15T10:00:00Z
updated_at:              2026-04-27T14:30:00Z (15s ago)
created_by_event:        12340
updated_by_event:        12345
```

**Row exists, `--json`:**
Full row as JSON for tooling.

**Row not yet materialized:**
```
case_posture row not yet materialized for vanderburge-v-knight-fannin
(case exists in legal.cases but no event has triggered _load_or_create_case_posture yet)
First inbound email.received with this case_slug will create the row.
```

**case_slug not in legal.cases:**
```
ERROR: case_slug 'unknown-case' not found in legal.cases.
```

---

## 8. `posture history` subcommand

```
fgp legal posture history --case-slug X [--limit 20]
```

Walks `legal.event_log` for `case_slug` in time order via the existing `idx_event_log_case_slug` partial index (Phase 0a-1).

### 8.1 Query

```sql
SELECT id, event_type, emitted_at, emitted_by, processed_at, processed_by,
       result->>'status' AS result_status
FROM legal.event_log
WHERE case_slug = :case_slug
ORDER BY emitted_at DESC
LIMIT :limit
```

### 8.2 Output

```
posture history for vanderburge-v-knight-fannin (last 20 events)

emitted_at              event_type           emitted_by                 processed  result_status
----------------------------------------------------------------------------------------------
2026-04-27 14:30:00Z   watchdog.matched     legal_dispatcher:v1        ✓          success
2026-04-27 14:30:00Z   email.received       legal_mail_ingester:v1     ✓          success
2026-04-27 09:12:00Z   email.received       legal_mail_ingester:v1     ✓          success
...
```

Read-only. No DB writes.

---

## 9. `dead-letter list` and `dead-letter purge`

### 9.1 `dead-letter list [--limit 50]`

Read-only. Reads `legal.dispatcher_dead_letter` ordered by `dead_lettered_at DESC`. Output table: id, original_event_id, event_type, case_slug, final_error (truncated), attempts, age.

### 9.2 `dead-letter purge --before YYYY-MM-DD --confirm`

Plan-by-default; `--confirm` to execute.

**Plan mode:**
```sql
SELECT COUNT(*) FROM legal.dispatcher_dead_letter WHERE dead_lettered_at < :before;
```

Output: `Would delete N rows. Pass --confirm to execute.`

**Execute mode (`--confirm`):**
```sql
DELETE FROM legal.dispatcher_dead_letter WHERE dead_lettered_at < :before;
```

Bilateral.

### 9.3 Validation guards

- `--before` must parse as ISO date (`YYYY-MM-DD`); reject otherwise (exit 9 — same code as Phase 0a-3 backfill `--since` parse error)
- `--before` cannot be in the future (exit 11)
- `--before` cannot be within last 24 hours (exit 12 — defensive: prevent accidental purge of fresh dead-letters operator may still need)

---

## 10. Health endpoint — `legal_dispatcher_health.py`

`GET /api/internal/legal/dispatcher/health`

### 10.1 Auth (matches `legal_mail_health.py` from PR #247 verbatim)

- `Authorization: Bearer <internal_api_bearer_token>`
- `X-Fortress-Ingress: command_center`
- `X-Fortress-Tunnel-Signature: <internal_api_bearer_token>`

`secrets.compare_digest` for timing-safe comparison. Failure raises `HTTPException(401)` for bearer issues, `HTTPException(403)` for ingress/signature.

### 10.2 Pydantic response models (`extra='forbid'`)

```python
OverallStatus = Literal["ok", "degraded", "disabled", "lagging"]

class QueueStats(BaseModel):
    unprocessed_total: int
    oldest_unprocessed_age_sec: float | None
    processed_last_hour: int
    failed_last_hour: int
    dead_lettered_last_hour: int
    mean_handler_ms: float | None
    p99_handler_ms: float | None

class RouteSummary(BaseModel):
    event_type: str
    handler: str          # "module.function" composite
    enabled: bool
    max_retries: int

class PauseStatus(BaseModel):
    paused: bool
    paused_at: datetime | None
    paused_by: str | None
    reason: str | None

class HealthSummary(BaseModel):
    total_routes: int
    enabled_routes: int
    paused: bool
    overall_status: OverallStatus

class LegalDispatcherHealthResponse(BaseModel):
    service: Literal["legal_dispatcher"]
    version: Literal["v1"]
    dispatcher_enabled: bool
    checked_at: datetime
    overall_status: OverallStatus
    queue: QueueStats
    routes: list[RouteSummary]
    pause: PauseStatus
    summary: HealthSummary
```

### 10.3 Status semantics

| status | trigger |
|---|---|
| `disabled` | `settings.legal_dispatcher_enabled is False` |
| `lagging` | flag True + `oldest_unprocessed_age_sec > LAG_THRESHOLD_SEC` (PROPOSED 60s) |
| `degraded` | flag True + (`failed_last_hour > 0` OR `dead_lettered_last_hour > 0`) |
| `ok` | flag True + lag within threshold + no recent failures |

Pause state is reflected in `pause.paused` + `summary.paused`; does NOT change `overall_status` (paused is a deliberate operator state, not a degradation signal).

### 10.4 HTTP semantics

| status | meaning |
|---|---|
| 200 | response delivered (check `overall_status` body field) |
| 401 | missing/bad bearer |
| 403 | wrong ingress or tunnel signature |
| 503 | DB connection failure (service can't evaluate itself) |

### 10.5 Router registration in `main.py`

```python
from backend.api import legal_dispatcher_health as legal_dispatcher_health_api
...
app.include_router(
    legal_dispatcher_health_api.router,
    prefix="/api/internal",
    tags=["Internal Health — Legal Dispatcher"],
)
```

Adjacent to `legal_mail_health` registration (PR #247).

---

## 11. Sub-phase commit decomposition

Five commits on `feat/flos-phase-1-4-cli-health` (mirrors Phase 0a-3 PR #247 5-sub-phase pattern):

| sub-phase | scope | commit boundary |
|---|---|---|
| **1-4A** | CLI module skeleton + argparse structure + `status` subcommand + output formatters | All wiring + 1 read-only command |
| **1-4B** | `pause` / `resume` mutators with bilateral writes + operator resolution chain | First mutators; bilateral discipline established |
| **1-4C** | `replay` subcommand (plan-by-default + `--confirm` + dead-letter-emitted refusal guard) | Stateful mutator with terraform-style plan |
| **1-4D** | `posture get` + `posture history` + `dead-letter list` + `dead-letter purge` | Read commands + Q3-LOCKED purge path |
| **1-4E** | health endpoint + Pydantic response models + main.py router registration | HTTP twin; closes operator surface |

Each commit surfaces before the next per the established discipline.

---

## 12. Verification posture for the Phase 1-4 PR

This PR ships operator surface only — no schema changes, no service changes, no flag flips.

What CAN be verified now:
- ✅ Code parses (Python syntax)
- ✅ Schema dependency intact — Phase 1-1 (PR #249) provides the 5 tables CLI reads/writes
- ✅ Service dependency intact — Phase 1-2 (PR #252) + Phase 1-3 (PR #254) provide the dispatcher worker + handlers that populate the data CLI surfaces
- ✅ Default OFF preserved — no flag flip in this PR
- ✅ Health endpoint returns `disabled` status when flag off (distinct from `degraded`)
- ✅ CLI mutators work against DBs regardless of worker state (pause writes the table; the running worker reads it on next cycle)

What's verified by Phase 1-5 cutover:
- `fgp legal dispatcher status` shows queue depth + last-hour metrics correctly
- `curl /api/internal/legal/dispatcher/health` returns `overall_status: "ok"` after flag flip
- First `email.received` event materializes a `case_posture` row (verifiable via `fgp legal posture get`)

What's verified by Phase 1-6 24h soak:
- Health endpoint stays `ok` over time (no false-positive `lagging` or `degraded`)
- Pause/resume affect dispatcher behavior as expected
- Dead-letter purge respects the 24-hour floor (no accidental data loss)

---

## 13. Phase 1-5 cutover sequence

After Phase 1-4 PR merges, operator runs:

1. `fgp legal dispatcher status`
   - Verify all 6 routes loaded; queue empty; flag still false
2. `curl -H "Authorization: Bearer <token>" -H "X-Fortress-Ingress: command_center" -H "X-Fortress-Tunnel-Signature: <token>" https://internal/api/internal/legal/dispatcher/health`
   - Verify `overall_status: "disabled"` baseline; pause empty; queue zero
3. Edit `.env`: `LEGAL_DISPATCHER_ENABLED=true`
4. `systemctl restart fortress-arq-worker` (or equivalent)
5. Wait ~5s for first poll cycle
6. `curl /api/internal/legal/dispatcher/health` again
   - Verify `overall_status: "ok"`; `dispatcher_enabled: true`
7. Wait for first inbound `email.received` event (should be quick once Captain/legal_mail_ingester is running)
8. `fgp legal posture get --case-slug <active-case>` — verify row materialized

Phase 1-6 24h soak follows.

---

## 14. Cross-references

- Parent (LOCKED): `FLOS-phase-1-state-store-design-v1.1.md` §8 (operator surface)
- Predecessor pattern: PR #247 Phase 0a-3 (CLI + health endpoint) — this PR mirrors verbatim
- Schema: PR #249 (`feat/flos-phase-1-1-schema`) — 5 tables CLI reads + writes
- Service: PR #252 Phase 1-2 (dispatcher worker) + PR #254 Phase 1-3 (handlers populating case_posture)
- Producer: PR #246 Phase 0a-2 (legal_mail_ingester emits events the dispatcher processes; CLI's `posture history` walks legal.event_log filtered by case_slug)
- ADR-001 — bilateral mirror discipline (honored: pause/resume/replay/dead-letter purge all bilateral)
- ADR-002 — Spark 2 placement (CLI runs anywhere with DB credentials; health endpoint runs in FastAPI on Spark with backend)
- Issue #204 — alembic chain divergence (no migrations in 1-4)

---

## 15. Status flag

| element | status |
|---|---|
| Goals + scope (§1) | **LOCKED** by design v1.1 §8 |
| File structure (§2) | **LOCKED** — 2 new files + 1 modified |
| CLI module structure (§3) | **LOCKED** — argparse mirrors PR #247 |
| `status` (§4) | **LOCKED** — read-only; 4 query sources |
| `pause`/`resume` (§5) | **LOCKED** — singleton table; bilateral |
| `replay` (§6) | **LOCKED** — plan-by-default + dead-letter-emitted refusal guard |
| `posture get`/`history` (§7,§8) | **LOCKED** — read-only |
| `dead-letter list`/`purge` (§9) | **LOCKED** — Q3 operator-triggered + 24h floor guard |
| Health endpoint (§10) | **LOCKED** — auth + Pydantic shape mirror PR #247; status semantics + LAG_THRESHOLD PROPOSED |
| Sub-phase decomposition (§11) | **PROPOSED** — five commits 1-4A → 1-4E |
| Verification posture (§12) | **LOCKED** — same discipline as #247/#252/#254 |
| Phase 1-5 cutover sequence (§13) | **LOCKED** — 8 explicit operator steps |

Operator review next — close §11 sub-phase boundaries (likely no changes needed; mirrors precedent), confirm §10.3 LAG_THRESHOLD_SEC=60 PROPOSED, then authorize Phase 1-4A skeleton commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
