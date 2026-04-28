# FLOS Phase 1-3 — Event Handler Implementations (Implementation Spec)

**Status:** PROPOSED — operator review pending before Phase 1-3A
**Author:** assistant (with operator)
**Date:** 2026-04-27
**Parent design:** `FLOS-phase-1-state-store-design-v1.1.md` §6 (event handlers) + §9 (source attribution) + §13 (principles 1, 4, 6)
**Predecessor spec:** `FLOS-phase-1-2-dispatcher-worker-implementation.md` §13 (Phase 1-3 next)
**Stacks on:** Phase 1-2 dispatcher worker (PR #252) → Phase 1-1 schema (#249) → Phase 0a stack (#247/#246/#245)
**Sequencing:** Phase 1-3 follows Phase 1-2 merge

---

## 1. Goals + scope boundary

Phase 1-3 populates the `_HANDLERS` dict in `legal_dispatcher.py` with **4 live handlers + 2 placeholder stubs**. After this PR ships, the dispatcher worker has a complete consumer surface — but it remains inert until Phase 1-5 cutover flips `LEGAL_DISPATCHER_ENABLED=true`.

**This is the first sub-phase where `case_posture` is mutated.** Principle 1 (events drive state) is enforced operationally from Phase 1-3 forward: only the dispatcher writes `case_posture` rows; every mutation cites `updated_by_event`.

**In scope (4 live handlers + 2 stubs):**
- `_handle_email_received` (1-3A) — emit `watchdog.matched` events; refresh `case_posture` audit timestamps
- `_handle_watchdog_matched` (1-3B) — aggregate `top_risk_factors` by `rule_id`; emit `operator.alert` for P1
- `_handle_operator_input` (1-3C) — direct `case_posture` field mutation via operator allowlist
- `_handle_dead_letter` (1-3D) — observability-only sink for re-emitted dispatcher.dead_letter events
- `_handle_vault_document_ingested` (1-3E) — placeholder stub; `dispatcher_routes.enabled = FALSE`
- `_handle_council_deliberation_complete` (1-3E) — placeholder stub; `dispatcher_routes.enabled = FALSE`

**Out of scope (deferred to Phase 1-4):**
- Operator CLI — `fgp legal dispatcher status / pause / resume / replay / posture get / dead-letter list/purge`
- Health endpoint — `GET /api/internal/legal/dispatcher/health`

**Out of scope (deferred to Phase 2+):**
- `procedural_phase` mutation logic in `_handle_email_received` — design v1.1 §6.1 LOCKED defers this; needs operator-managed `legal.procedural_phase_rules` table
- `operator.alert` event handler — Phase 1-3B emits the event but its consumer is Phase 2+
- Vault ingester producer (`vault.document_ingested` source) — Phase 2+ candidate
- Council audit migration to event_log — Phase 2+ work

**Handler signature (LOCKED):**

```
async def _handle_<event_type>(event: dict[str, Any]) -> dict[str, Any]
```

Returns a JSONB-serializable result dict for `legal.event_log.result`. The dispatcher's `_mark_processed()` (Phase 1-2 §5.2) writes the return value verbatim.

**Idempotency requirement (Principle 6 LOCKED):** every handler must produce the same `case_posture` state for the same input event sequence regardless of when it runs. Verified by inspection during 1-3 sub-phase reviews and by Phase 1-6 24h soak.

---

## 2. File structure

| file | role | new/modified |
|---|---|---|
| `backend/services/legal_dispatcher.py` | extended — handler functions added in-file per Q5 LOCKED Option B; `_HANDLERS` dict populated at end of module | MODIFIED |

**No new files.** All Phase 1-3 changes are additions to `legal_dispatcher.py`. Phase 1-4 introduces:
- `backend/scripts/legal_dispatcher_cli.py` (new)
- `backend/api/legal_dispatcher_health.py` (new)

---

## 3. Common handler infrastructure

Three shared helpers ship in 1-3A (used by 1-3A, 1-3B, 1-3C). All bilateral, all reuse the Phase 1-2 `_record_attempt` forced-id + setval pattern.

### 3.1 `_load_or_create_case_posture(case_slug, event_id) -> dict[str, Any] | None`

Load the existing `case_posture` row OR create a new row with Phase 1-1 schema defaults. Returns the row dict, or `None` if `case_slug` does not match an active case in `legal.cases`.

Logic:
1. SELECT from `legal.case_posture` WHERE `case_slug = :case_slug` (LegacySession)
2. If found → return as dict
3. If not found:
   - Verify `case_slug` exists in `legal.cases` (active matter)
   - If not → return `None`
   - If yes → INSERT new row with all Phase 1-1 defaults:
     - `procedural_phase = 'pre-suit'`
     - `theory_of_defense_state = 'drafting'`
     - `top_defense_arguments = '[]'`
     - `top_risk_factors = '{}'`
     - `posture_hash = _compute_posture_hash(...)`
     - `created_by_event = event_id`
     - `updated_by_event = event_id`
   - Bilateral write (forced-id + setval mirror)
   - Return the new row dict

This helper materializes `case_posture` lazily on the first event that observes a case. Phase 1-1 ships zero rows; rows accumulate as events flow.

### 3.2 `_bilateral_write_case_posture(case_slug, updates: dict, event_id: int) -> bool`

UPSERT pattern with COALESCE on unchanged fields. Updates only the columns named in `updates`; preserves all other columns.

Logic:
1. Build dynamic UPDATE SET clause from `updates` dict
2. Always include: `updated_by_event = :event_id`, `updated_at = NOW()`, `posture_hash = :new_hash`
3. Execute on LegacySession; commit
4. Mirror to ProdSession with same SET clause; log + don't raise on mirror failure (drift mode)
5. Return `True` iff legacy commit succeeded

Mirrors Phase 1-2 `_mark_processed` for the bilateral UPDATE pattern. The `updated_by_event` field is the Principle 4 audit anchor — every mutation cites the source event.

### 3.3 `_compute_posture_hash(posture_dict) -> str`

SHA-256 over a JSON-canonicalized projection of the **Phase 1-populated fields only**. Per design v1.1 §3 `posture_hash` discipline:

```
canonical_input = {
    "case_slug": ...,
    "procedural_phase": ...,
    "theory_of_defense_state": ...,
    "top_defense_arguments": ...,
    "top_risk_factors": ...,
}
hash_value = sha256(json.dumps(canonical_input, sort_keys=True, separators=(',', ':'))).hexdigest()
```

Phase 2+ field additions extend the canonicalization input; the field set is versioned in code. `posture_hash_version` column add (PROPOSED in design v1.1 §3) is deferred unless drift detection is needed before Phase 2 ships those fields.

---

## 4. Handler 1-3A — `_handle_email_received`

**Per design v1.1 §6.1 LOCKED scope.**

Triggered by `legal_mail_ingester:v1` on every inbound legal email (Phase 0a-2 producer).

**v1.1 LOCKED scope (this PR):**

```
async def _handle_email_received(event: dict) -> dict:
    event_id = int(event["id"])
    case_slug = event.get("case_slug")
    payload = event.get("event_payload") or {}

    # Skip if no case match
    if not case_slug:
        return {"status": "skipped_no_case_slug"}
    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {"status": "skipped_no_active_case", "case_slug": case_slug}

    # Emit watchdog.matched events for each match in payload
    matches = payload.get("watchdog_matches") or []
    emitted = 0
    for match in matches:
        new_event_id = await _emit_watchdog_event(case_slug, match, event_id)
        if new_event_id is not None:
            emitted += 1

    # Refresh audit timestamps on case_posture
    await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates={},  # no field changes — just timestamp + posture_hash refresh
        event_id=event_id,
    )

    return {
        "status": "success",
        "case_slug": case_slug,
        "watchdog_events_emitted": emitted,
    }
```

**Removed from v1.1 scope (deferred to Phase 2+):**
- `procedural_phase` mutation. v1's "if email pattern indicates phase advancement" was operator-defined rules without an operator-defined ruleset. Phase 2+ adds `legal.procedural_phase_rules` table + a separate handler that consumes it.

**Idempotency:** same event re-applied yields same `case_posture.updated_by_event` (last-writer-wins) and same `top_risk_factors` (1-3B handler is the one that mutates that field, not 1-3A). Re-emitted watchdog events are deduplicated by event_log's natural ordering — re-running 1-3A would emit duplicate watchdog.matched events. **Phase 1-3A intentionally does NOT dedupe re-emission** because dispatcher's polling-exclusion sub-query (Phase 1-2 §5.1) already excludes processed events; under the no-event-lost guarantee, re-emission only happens during recovery, and idempotent 1-3B handlers absorb it.

---

## 5. Handler 1-3B — `_handle_watchdog_matched`

**Per design v1.1 §6.2 LOCKED scope (per-rule aggregation).**

Triggered by 1-3A re-emission when a watchdog rule matches.

```
async def _handle_watchdog_matched(event: dict) -> dict:
    event_id = int(event["id"])
    case_slug = event.get("case_slug")
    payload = event.get("event_payload") or {}

    rule_id = payload.get("rule_id")
    if not case_slug or not rule_id:
        return {"status": "skipped_missing_required_fields"}

    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {"status": "skipped_no_active_case", "case_slug": case_slug}

    # Aggregate by rule_id (LOCKED v1.1 §6.2)
    top_risk_factors = posture.get("top_risk_factors") or {}
    now_iso = datetime.now(timezone.utc).isoformat()
    if rule_id in top_risk_factors:
        existing = top_risk_factors[rule_id]
        existing["last_match_at"] = now_iso
        existing["match_count"] = int(existing.get("match_count", 0)) + 1
    else:
        top_risk_factors[rule_id] = {
            "rule_id": rule_id,
            "rule_name": payload.get("rule_name"),
            "severity": payload.get("severity"),
            "first_match_at": now_iso,
            "last_match_at": now_iso,
            "match_count": 1,
        }

    await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates={"top_risk_factors": top_risk_factors},
        event_id=event_id,
    )

    # Emit operator.alert for P1 severity (consumer is Phase 2+)
    if payload.get("severity") == "P1":
        await _emit_operator_alert(case_slug, payload, event_id)

    return {
        "status": "success",
        "rule_id": rule_id,
        "match_count": top_risk_factors[rule_id]["match_count"],
    }
```

**`top_risk_factors` representation (LOCKED v1.1 §6.2):** dict keyed by `rule_id`, NOT a capped append list. Bounded by active-rule count (~10–30 per case). Operator surface (Phase 1-4 CLI / Phase 2+ dashboard) reads "rule X matched 7 times, last 5m ago" — actionable signal.

**Idempotency:** re-applying the same event increments `match_count` twice. **This is acceptable because**:
- The dispatcher's polling-exclusion sub-query prevents same-event re-application unless attempts have been wiped (recovery operation)
- Replay is operator-driven; `match_count` reflects emissions, which is the desired audit semantic
- Phase 1-6 24h soak detects unbounded `match_count` growth as a recovery red flag

If stricter idempotency is needed in Phase 2+, switch to "max(match_count, current+1)" semantics or add a `(event_id, rule_id)` UNIQUE constraint.

---

## 6. Handler 1-3C — `_handle_operator_input`

**Per design v1.1 §6.3.**

Triggered by future operator CLI commands (Phase 2+). For Phase 1-3, the route is wired but live operator commands ship in Phase 2+ — only test-fixture events exercise this handler during 1-3 development.

```
async def _handle_operator_input(event: dict) -> dict:
    event_id = int(event["id"])
    payload = event.get("event_payload") or {}

    command = payload.get("command")
    case_slug = payload.get("case_slug")
    fields = payload.get("fields") or {}

    if command != "set_field":
        return {"status": "skipped_unknown_command", "command": command}
    if not case_slug:
        return {"status": "skipped_missing_case_slug"}
    if not fields:
        return {"status": "skipped_no_fields"}

    posture = await _load_or_create_case_posture(case_slug, event_id)
    if posture is None:
        return {"status": "skipped_no_active_case", "case_slug": case_slug}

    # Validate field allowlist
    invalid = [f for f in fields if f not in OPERATOR_INPUT_ALLOWED_FIELDS]
    if invalid:
        return {"status": "rejected_invalid_fields", "invalid": invalid}

    # Apply mutations directly (CHECK constraints at DB layer enforce values)
    await _bilateral_write_case_posture(
        case_slug=case_slug,
        updates=fields,
        event_id=event_id,
    )

    return {
        "status": "success",
        "case_slug": case_slug,
        "fields_updated": list(fields.keys()),
    }
```

### 6.1 `OPERATOR_INPUT_ALLOWED_FIELDS` — **OPERATOR DECISION REQUIRED before 1-3C commit**

Operator must lock the allowlist of `case_posture` columns that `operator.input` may mutate. Recommended Phase 1-3 default:

| field | allow Phase 1-3? | rationale |
|---|---|---|
| `procedural_phase` | YES | operator override path until Phase 2+ rule table ships |
| `theory_of_defense_state` | YES | operator-driven workflow gate |
| `top_defense_arguments` | YES | operator-curated list |
| `exposure_low` / `mid` / `high` | YES | Phase 2+ exposure model writes are PROPOSED; operator override desired meanwhile |
| `leverage_score` | YES | operator-set until Phase 2+ Council projection |
| `opposing_counsel_profile` | YES | operator-curated |
| `top_risk_factors` | **NO** | dispatcher-managed via `_handle_watchdog_matched`; operator override would corrupt aggregation |
| `last_council_consensus` / `last_council_at` | NO | Phase 2+ council handler writes these; protect from operator races |
| `next_deadline_date` / `next_deadline_action` | NO | Phase 2+ deadline projection writes these |
| `case_slug` | NO | primary key, immutable |
| `created_at` / `updated_at` / FKs / `posture_hash` | NO | system-managed |

**PROPOSED allowlist:** `{procedural_phase, theory_of_defense_state, top_defense_arguments, exposure_low, exposure_mid, exposure_high, leverage_score, opposing_counsel_profile}`

Operator lock required before 1-3C commit.

---

## 7. Handler 1-3D — `_handle_dead_letter`

**Per design v1.1 §6.6 — observability ONLY.**

```
async def _handle_dead_letter(event: dict) -> dict:
    event_id = int(event["id"])
    payload = event.get("event_payload") or {}

    logger.warn(
        "legal_dispatcher_dead_letter_observed",
        event_id=event_id,
        original_event_id=payload.get("original_event_id"),
        original_event_type=payload.get("original_event_type"),
        final_error=payload.get("final_error"),
        attempts=payload.get("attempts"),
    )

    return {
        "status": "observed",
        "original_event_id": payload.get("original_event_id"),
    }
```

**Critical constraints:**
- Does NOT emit further events (avoid infinite loop — a failure in this handler's own dispatch could itself dead-letter, which would re-emit, ad infinitum)
- Does NOT write to `case_posture` (dead-letters are observability, not state)
- Does NOT write to `dispatcher_dead_letter` table (Phase 1-2 `_insert_dead_letter_log` already did that in step 3 of the 4-step sequence; double-writing would create duplicate audit rows)
- Returns observation result; dispatcher's `_mark_processed` writes it to `event_log.result`

**Idempotency:** trivially idempotent (no state mutation; only structured logging).

---

## 8. Handler 1-3E — Placeholder stubs

Both routes are seeded `enabled = FALSE` in Phase 1-1 schema. The handlers exist so the `_HANDLERS` dict has all 6 keys covered (avoids `handler_not_registered` skips in observability when these event types are emitted prematurely).

```
async def _handle_vault_document_ingested(event: dict) -> dict:
    return {
        "status": "placeholder_not_implemented",
        "event_type": "vault.document_ingested",
        "note": "Vault ingester producer ships in Phase 2+ candidate work",
    }

async def _handle_council_deliberation_complete(event: dict) -> dict:
    return {
        "status": "placeholder_not_implemented",
        "event_type": "council.deliberation_complete",
        "note": "Council audit migration to event_log is Phase 2+ work",
    }
```

Activated when their producer services ship (Phase 2+ for Vault ingester; Phase 2+ for Council audit migration). At that time the operator runs:
```sql
UPDATE legal.dispatcher_routes
SET enabled = TRUE
WHERE event_type IN ('vault.document_ingested', 'council.deliberation_complete');
```

…and replaces the stub bodies with real handlers in a Phase 2+ PR.

---

## 9. `_HANDLERS` dict population

At the **end** of `legal_dispatcher.py`, after all handler functions are defined, replace the empty `_HANDLERS = {}` with:

```
_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "email.received":                _handle_email_received,
    "watchdog.matched":              _handle_watchdog_matched,
    "operator.input":                _handle_operator_input,
    "dispatcher.dead_letter":        _handle_dead_letter,
    "vault.document_ingested":       _handle_vault_document_ingested,
    "council.deliberation_complete": _handle_council_deliberation_complete,
}
```

The 6 keys correspond exactly to the 6 seed rows in `legal.dispatcher_routes` (Phase 1-1 r3c4d5e6f7g8 migration). 4 enabled live + 2 placeholder-disabled. Order in the dict is purely cosmetic; runtime lookup is O(1).

---

## 10. `case_posture` mutation discipline

**Every handler that mutates `case_posture` must:**
1. Cite `updated_by_event = event["id"]` (Principle 4 — source attribution)
2. Bump `updated_at = NOW()` (audit timeline)
3. Recompute `posture_hash` AFTER all field mutations are applied
4. Bilateral write (legacy first, prod mirror second; mirror failure logs warning, doesn't raise)
5. Be idempotent under same-event re-application (Principle 6)

The shared helpers (`_bilateral_write_case_posture` + `_compute_posture_hash`) enforce items 1–4. Item 5 is per-handler responsibility verified by inspection.

**Principle 1 enforcement** (LOCKED): no other code path in Phase 1 writes to `case_posture`. The dispatcher is the single writer; if it is paused, `case_posture` is frozen. Operator manual mutations route through `operator.input` events, not direct SQL.

---

## 11. Watchdog event emission (1-3A specific)

`_handle_email_received` emits 0..N `watchdog.matched` events into `legal.event_log`. Each emission is bilateral (forced-id + setval pattern reuse from Phase 0a-2 §10 + Phase 1-2 1-2D §6 step 4).

```
async def _emit_watchdog_event(case_slug, match: dict, source_event_id: int) -> Optional[int]:
    payload = {
        "rule_id": match.get("rule_id"),
        "rule_name": match.get("rule_name"),
        "severity": match.get("severity"),
        "match_type": match.get("match_type"),
        "search_term": match.get("search_term"),
        "source_event_id": source_event_id,
    }
    # Insert legal.event_log row with event_type='watchdog.matched'
    # emitted_by = DISPATCHER_VERSIONED ('legal_dispatcher:v1')
    # Bilateral with forced-id + setval on legal.event_log_id_seq
    # Returns new event_id or None on legacy failure
    ...
```

**Producer tag:** `emitted_by = DISPATCHER_VERSIONED` (the dispatcher is the producer of these re-emitted events). The original email's `legal_mail_ingester:v1` tag is preserved in the `source_event_id` payload field for the audit chain.

Re-emitted events join the polling queue. The dispatcher picks them up on the next cycle and routes via `_HANDLERS["watchdog.matched"] = _handle_watchdog_matched`.

A similar `_emit_operator_alert` helper (1-3B) emits `operator.alert` events; its consumer is Phase 2+, so for Phase 1-3 the events accumulate in `event_log` but no handler processes them (the dispatcher records `handler_not_registered` skip per clarification #2).

---

## 12. Sub-phase commit decomposition

Five commits on `feat/flos-phase-1-3-event-handlers`:

| sub-phase | scope | commit boundary |
|---|---|---|
| **1-3A** | `_load_or_create_case_posture` + `_bilateral_write_case_posture` + `_compute_posture_hash` shared helpers + `_emit_watchdog_event` helper + `_handle_email_received` | First case_posture writes; helper foundation |
| **1-3B** | `_handle_watchdog_matched` + per-rule aggregation logic + `_emit_operator_alert` helper | Second writer to case_posture; consumes 1-3A's re-emissions |
| **1-3C** | `_handle_operator_input` + `OPERATOR_INPUT_ALLOWED_FIELDS` constant + field validation | Operator override path; allowlist locked per §6.1 |
| **1-3D** | `_handle_dead_letter` (observability-only; no state mutation) | Closes the dead-letter loop |
| **1-3E** | `_handle_vault_document_ingested` stub + `_handle_council_deliberation_complete` stub + `_HANDLERS` dict population | All 6 entries wired; dispatcher functionally complete |

Each commit surfaces before the next per the established discipline.

---

## 13. Verification posture for the Phase 1-3 PR

This PR ships handler code only — no schema changes, no operator surface, no CI tests (those land in a separate sub-PR per the discipline established in #246/#247/#252).

What CAN be verified now:
- ✅ Code parses (Python syntax)
- ✅ Schema dependency intact — Phase 1-1 (PR #249) creates the 5 tables this PR writes to
- ✅ Service dependency intact — Phase 1-2 (PR #252) provides the dispatcher worker that calls into `_HANDLERS`
- ✅ Producer dependency intact — Phase 0a-2 (PR #246) emits `email.received` events that 1-3A consumes
- ✅ Default OFF preserved — `LEGAL_DISPATCHER_ENABLED=false`; no flag flip in this PR
- ✅ `_HANDLERS` populated with 6 entries matching `dispatcher_routes` seed exactly

What's verified by Phase 1-4:
- CLI surfaces `case_posture` rows for inspection (`fgp legal posture get --case-slug X`)
- HTTP health endpoint returns dispatcher state for monitoring

What's verified by Phase 1-5 cutover + 1-6 24h soak:
- `case_posture` rows materialize for active cases on first `email.received` event
- `top_risk_factors` aggregation produces per-rule entries with correct match_count + last_match_at
- Bilateral parity holds across `case_posture` (fortress_db row count = fortress_prod row count)
- Idempotency holds — replay produces same `case_posture` state
- `posture_hash` stable across identical inputs
- No false-positive dead-letters from handler exceptions

---

## 14. What Phase 1-4 adds next

Two new files:

1. `backend/scripts/legal_dispatcher_cli.py` — operator CLI (argparse, mirrors `legal_mail_ingester_cli.py` from PR #247)
   - `fgp legal dispatcher status` — read dispatcher_routes + dispatcher_event_attempts aggregations + queue lag
   - `fgp legal dispatcher pause / resume` — bilateral write to dispatcher_pause
   - `fgp legal dispatcher replay --event-id N --confirm` — clear processed_at + dispatcher_event_attempts rows
   - `fgp legal dispatcher dead-letter list` — read dispatcher_dead_letter ordered by dead_lettered_at DESC
   - `fgp legal dispatcher dead-letter purge --before YYYY-MM-DD --confirm` — bilateral delete
   - `fgp legal posture get --case-slug X [--json]` — read case_posture row
   - `fgp legal posture history --case-slug X [--limit 20]` — walk event_log for case

2. `backend/api/legal_dispatcher_health.py` — programmatic health endpoint
   - `GET /api/internal/legal/dispatcher/health` — JSON twin of CLI status
   - Auth: Bearer + X-Fortress-Ingress + X-Fortress-Tunnel-Signature (matches `legal_mail_health.py`)
   - Response: `overall_status: "ok" | "degraded" | "disabled" | "lagging"`

Phase 1-4 PR opens after Phase 1-3 PR merges.

---

## 15. Open items requiring operator decision before commit

| sub-phase | item | required by |
|---|---|---|
| **1-3C** | `OPERATOR_INPUT_ALLOWED_FIELDS` allowlist (§6.1) — PROPOSED 8 fields; operator may revise | Before 1-3C commit |

All other sub-phases derive their behavior from LOCKED design v1.1 elements + Phase 1-2 patterns. No additional open items.

---

## 16. Cross-references

- Parent (LOCKED): `FLOS-phase-1-state-store-design-v1.1.md` §6 (event handlers), §9 (source attribution), §13 (principles 1, 4, 6)
- Predecessor spec: `FLOS-phase-1-2-dispatcher-worker-implementation.md` §13 (Phase 1-3 next)
- Schema: PR #249 (`feat/flos-phase-1-1-schema`) — case_posture + dispatcher_routes + dispatcher_event_attempts + dispatcher_dead_letter
- Service patterns: PR #252 (`feat/flos-phase-1-2-dispatcher-worker`) — `_record_attempt` bilateral + dispatch flow + `_HANDLERS` dict reference
- Producer: PR #246 (`feat/flos-phase-0a-2-service`) — `legal_mail_ingester` emits `email.received` events that 1-3A handler consumes
- ADR-001 — bilateral mirror discipline
- ADR-002 — Captain + Sentinel on Spark 2 (legal_dispatcher co-locates)
- Issue #204 — alembic chain divergence (no migrations in 1-3; respected)

---

## 17. Status flag

| element | status |
|---|---|
| Goals + scope (§1) | **LOCKED** by design v1.1 §6 |
| File structure (§2) | **LOCKED** — single-file extension only |
| Common helpers (§3) | **PROPOSED** — operator may iterate before 1-3A |
| `_handle_email_received` scope (§4) | **LOCKED** — design v1.1 §6.1 (no procedural_phase mutation) |
| `_handle_watchdog_matched` aggregation (§5) | **LOCKED** — design v1.1 §6.2 per-rule dict |
| `_handle_operator_input` flow (§6) | **LOCKED**; allowlist (§6.1) **OPEN** for operator decision |
| `_handle_dead_letter` constraints (§7) | **LOCKED** — observability-only |
| Placeholder stubs (§8) | **LOCKED** — return `placeholder_not_implemented` |
| `_HANDLERS` dict (§9) | **LOCKED** — 6 keys matching Phase 1-1 seed |
| Mutation discipline (§10) | **LOCKED** — Principles 1, 4, 6 |
| Watchdog re-emission (§11) | **LOCKED** — bilateral with forced-id + setval |
| Sub-phase decomposition (§12) | **PROPOSED** — five commits 1-3A → 1-3E |
| Verification posture (§13) | **LOCKED** — same discipline as #246/#247/#252 |

Operator review next — close §3 helpers + §6.1 allowlist + §12 sub-phase boundaries, then authorize Phase 1-3A skeleton commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
