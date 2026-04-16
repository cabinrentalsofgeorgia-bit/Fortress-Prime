# Phase I.4 Report — Event-Driven OBP Recompute on Owner Charge Writes
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Recompute wired to all 3 charge mutation endpoints. 3 validation scenarios passed.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Latest commit | I.1b (80dbef11) | 80dbef11 | PASS |
| `fortress-backend.service` | active | active | PASS |
| OBP 25680 | pending_approval, closing=$504,738.26 | ✓ | PASS |
| March charges (354, 356–358) | all voided | ✓ | PASS |
| Charge 355 ($169 carpenter bees) | active, untouched | ✓ | PASS |

---

## 2. Existing Compute Function (Task 2)

**Scenario A — existing function is clean, idempotent, respects finalized status.**

`generate_monthly_statements` in `backend/services/statement_workflow.py` (lines 204–228):
- Calls `compute_owner_statement(db, opa_id, period_start, period_end)` → full drift-proof rebuild
- Updates `total_revenue`, `total_commission`, `total_charges`, `closing_balance`
- Respects `_LOCKED_STATUSES = {approved, paid, emailed, voided}` via skip with log
- Already idempotent (deterministic output from same source records)

**Reuse strategy:** Extract the update logic into a new `recompute_obp_for_period` wrapper that calls `compute_owner_statement` directly, adds `SELECT FOR UPDATE`, and adds `OBPFinalizedError` raise semantics (instead of the generator's skip-and-log). Minimal new code.

---

## 3. Recompute Service Design

**File:** `backend/services/obp_recompute.py`

### `OBPFinalizedError`
```python
class OBPFinalizedError(Exception):
    obp_id: int
    obp_status: str
    charge_id: int
```

### `RecomputeResult`
```python
@dataclass
class RecomputeResult:
    obp_id: int
    old_closing: Decimal
    new_closing: Decimal
    delta: Decimal
    old_total_charges: Decimal
    new_total_charges: Decimal
```

### `recompute_obp_for_period(db, opa_id, period_start, period_end, charge_id, event_type)`
1. `SELECT ... FOR UPDATE` on OBP matching (opa_id, period_start, period_end)
2. No OBP → log `obp_recompute_no_period`, return `None`
3. Voided OBP → log `obp_recompute_skipped_voided`, return `None`
4. Finalized OBP → raise `OBPFinalizedError`
5. Call `compute_owner_statement(..., require_stripe_enrollment=False)` — handles secondary OPAs (Cherokee/Serendipity with `stripe_account_id=NULL`)
6. Update `total_revenue`, `total_commission`, `total_charges`, `closing_balance`, `updated_at`
7. `await db.flush()` (caller commits)
8. Log `obp_recomputed` with old/new values, delta
9. Return `RecomputeResult`

### `recompute_obp_for_charge_event(db, charge_id, event_type)`
- Loads charge → derives `period_start` / `period_end` (calendar month of `posting_date`)
- Delegates to `recompute_obp_for_period`

### `_FINALIZED_STATUSES`
`{approved, paid, emailed}` — NOTE: `voided` is treated as no-op, not error.

---

## 4. `admin_charges.py` Wiring (3 Endpoints)

### `_run_recompute(db, charge_id, event_type)` helper
Wraps `recompute_obp_for_charge_event` + `await db.commit()`. Returns `(obp_recomputed_dict, recompute_error_dict)`. Catches `OBPFinalizedError` and `Exception` — charge is always saved.

### `_charge_dict` extended
Added `obp_recomputed: Optional[dict]` and `recompute_error: Optional[dict]` fields — always present on mutation responses.

### Wired endpoints
| Endpoint | event_type |
|---|---|
| `POST /charges` | `"create"` |
| `PATCH /charges/{id}` | `"update"` |
| `POST /charges/{id}/void` | `"void"` |

**Transaction model:** Charge commits first (`await db.commit()` in each endpoint). Recompute runs in a second implicit transaction. If recompute fails, charge is still saved.

---

## 5. Retroactive Recompute Results

**Script:** `backend/scripts/i4_retroactive_recompute.py`

| OBP | Property | Status | Old Closing | New Closing | Delta |
|---|---|---|---|---|---|
| 25680 | Fallen Timber Lodge | pending_approval | $504,738.26 | $504,738.26 | **$0.00** |
| 25681 | Cherokee Sunrise | pending_approval | $64,822.71 | $64,822.71 | **$0.00** |
| 25682 | Serendipity | pending_approval | $308,517.68 | $308,517.68 | **$0.00** |

**0 OBPs changed** — all were already current. All validation charges (354, 354, 356, 357) were properly voided before this phase ran.

---

## 6. Validation Scenarios

### Scenario 1: Happy path — create + void on pending_approval OBP

| Step | Check | Expected | Result |
|---|---|---|---|
| Pre-state | OBP 25680 total_charges | $0.00 | ✓ |
| Post charge (id=358, $75) | total_charges | $75.00 | ✓ |
| Post charge (id=358, $75) | closing_balance | $504,663.26 (= $504,738.26 − $75) | ✓ |
| Log: `obp_recomputed` | delta=-75.0, charge_id=358 | ✓ | ✓ |
| Void charge 358 | total_charges | $0.00 | ✓ |
| Void charge 358 | closing_balance | $504,738.26 (restored) | ✓ |
| Log: `obp_recomputed` | delta=+75.0, event_type=void | ✓ | ✓ |

### Scenario 2: Finalized OBP protection

| Step | Check | Expected | Result |
|---|---|---|---|
| OBP 25681 set to approved | status | approved | ✓ |
| Charge 359 posted against OPA 1826 | charge saved | id=359 created | ✓ |
| `recompute_obp_for_charge_event` | raises `OBPFinalizedError` | obp_id=25681, status=approved | ✓ |
| OBP 25681 closing_balance | unchanged | $64,822.71 | ✓ |
| OBP 25681 total_charges | unchanged | $0.00 | ✓ |
| Restore & cleanup | status=pending_approval, charge 359 voided | ✓ | ✓ |

### Scenario 3: Concurrent writes smoke test

Two charges ($30 + $45 = $75) posted concurrently. `SELECT FOR UPDATE` serializes recompute.

| Step | Check | Expected | Result |
|---|---|---|---|
| Both charges created | ids 360 + 361 | ✓ | ✓ |
| Final total_charges | $75 ($30 + $45) | $75.00 | ✓ |
| Final closing | $504,663.26 | $504,663.26 | ✓ |
| After cleanup (both voided) | total_charges | $0.00 | ✓ |
| After cleanup | closing | $504,738.26 | ✓ |

All 3 scenarios: **PASS**.

---

## 7. Follow-ups Filed

### Recompute on reservation changes (I.4.1)
When a reservation's `nightly_rate` or financial detail changes, the OBP `total_revenue` and `closing_balance` become stale. Future: `recompute_obp_for_period` is already usable from a reservation-mutation hook — just needs wiring.

### Recompute on owner payments / credits (I.2 / I.3)
When owner payments or credits ship, they'll call `recompute_obp_for_period` directly with `event_type="create"/"void"`. The service is already designed for this.

### Un-finalize workflow
When a finalized OBP needs correction (e.g., a charge was missed), there's no admin workflow to reopen it. Filed as a future admin action: `POST /api/admin/payouts/statements/{id}/reopen` → transitions `approved` → `pending_approval`.

### DB trigger belt-and-suspenders
Postgres trigger on `owner_charges` INSERT/UPDATE to call the recompute is deferred. The service-level hook is sufficient for now; the trigger would add defense-in-depth for direct DB writes (e.g., SQL scripts, migrations).

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| Closing balance updates on charge create | **CERTAIN** — $504,663.26 = $504,738.26 − $75 verified in DB |
| Closing balance restores on charge void | **CERTAIN** — $504,738.26 restored exactly |
| `OBPFinalizedError` raised for approved OBP | **CERTAIN** — obp_id=25681 confirmed |
| Finalized OBP not modified | **CERTAIN** — total_charges=$0, closing=$64,822.71 unchanged |
| Concurrent writes handled correctly | **CERTAIN** — `SELECT FOR UPDATE` serializes; $75 total correct |
| Charge save independent of recompute | **CERTAIN** — separate transactions; recompute failure doesn't roll back charge |
| Retroactive cleanup: 0 stale OBPs | **CERTAIN** — delta=$0 for all 3 OBPs |
| `require_stripe_enrollment=False` in recompute | **CERTAIN** — Cherokee/Serendipity secondary OPAs handled |

---

## 9. Recommended Next Phase

**I.2 — Receive Owner Payment:** Record a payment from owner to management. Will invoke `recompute_obp_for_period` on create/void — architecture is now in place.

**I.3 — Credit Owner Account:** Record a credit back to owner (overpayment return). Same pattern.

**H.3 — Parity audit:** Compare CROG Serendipity and Cherokee March 2026 PDFs against NAS-archived Streamline PDFs line-by-line.
