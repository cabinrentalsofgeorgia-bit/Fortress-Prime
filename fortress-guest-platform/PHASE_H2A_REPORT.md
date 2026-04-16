# Phase H.2a Report — UI-Generate Filter Fix + April 2026 OBPs
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Filter removed, April 2026 OBPs generated for all 3 Gary OPAs.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Latest commit | I.4 (d8fe539b2) | d8fe539b2 | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| OPA 1824 | Stripe set | acct_1TMYCpK5ULr6Eoss | PASS |
| OPAs 1826, 1827 | stripe=NULL | NULL | PASS |
| March OBPs (25680–25682) | pending_approval | all 3 intact | PASS |
| Charge 355 ($169 carpenter-bee) | active | voided_at=NULL | PASS |
| April OBPs | 0 existing | 0 | PASS |

---

## 2. Filter Code Analysis (Task 2)

**Function:** `generate_monthly_statements` in `backend/services/statement_workflow.py`

**Location of filter:** Lines 133–137 (GENERATION path — creates OBPs for all OPAs covering a period).

**Original filter:**
```python
opa_result = await db.execute(
    select(OwnerPayoutAccount).where(
        OwnerPayoutAccount.stripe_account_id.isnot(None)
    )
)
```

**Effect:** Excluded OPAs 1826 (Cherokee) and 1827 (Serendipity) from all UI-driven generation. Staff clicking "Generate Statements" would get only one OBP for Gary (OPA 1824 / FTL).

**Scope:** Generation path only (not enrollment path, not a separate OBP-create guard). Idempotency is handled by `get_or_create_balance_period` — returning existing OBPs unchanged.

**Callers:** `POST /api/admin/payouts/statements/generate` (UI Generate button). No other callers.

**Second filter found:** `compute_owner_statement` (called inside the generation loop) also had an enrollment guard. The loop was catching `StatementComputationError(code="not_enrolled")` with `skipped_not_enrolled` status — but since the outer query was filtering first, this path never fired for OPAs 1826/1827. After removing the outer filter, the inner guard surfaced as errors. Fixed by passing `require_stripe_enrollment=False` at the call site.

---

## 3. Code Changes

### `backend/services/statement_workflow.py`

1. **Removed** `stripe_account_id IS NOT NULL` filter from `generate_monthly_statements` OPA query
2. **Added** `require_stripe_enrollment=False` to `compute_owner_statement` call inside the generation loop

### `backend/api/admin_statements_workflow.py`

1. Added `_PAY_ENABLED_STATUSES = frozenset(["approved", "paid"])`
2. Updated `_period_dict` signature: `def _period_dict(period, *, stripe_account_id: Optional[str] = None)`
3. `_period_dict` computes `pay_enabled = bool(stripe_account_id and period.status in _PAY_ENABLED_STATUSES)`
4. Added `_stripe_id_for_period(db, period)` async helper — does `db.get(OwnerPayoutAccount, period.owner_payout_account_id)` and returns `str(opa.stripe_account_id)` or `None`
5. Updated `list_statements`: preloads OPAs for all returned periods (no N+1) and passes `stripe_account_id` to `_period_dict`
6. Updated `get_statement`, `approve`, `void`, `mark_paid`, `mark_emailed`: each calls `_stripe_id_for_period` and passes result to `_period_dict`

---

## 4. UI Warning Addition

**File:** `apps/command-center/src/app/(dashboard)/admin/statements/page.tsx`

Added `AlertTriangle` import from lucide-react. In the Status cell of the statements table:

```tsx
<div className="flex items-center gap-1.5">
  <StatusBadge status={row.status} />
  {!row.pay_enabled && (
    <span title="Statement ready to view but not payable: Stripe not connected for this property owner."
          className="inline-flex text-amber-500">
      <AlertTriangle className="h-3.5 w-3.5" />
    </span>
  )}
</div>
```

**`types.ts`:** Added `pay_enabled: boolean` to `OwnerBalancePeriod`.

**TypeScript:** zero errors (`tsc --noEmit` clean). Build clean.

---

## 5. End-to-End Validation: April 2026 OBPs

**Trigger:** Direct call to `generate_monthly_statements(db, date(2026,4,1), date(2026,4,30))`.  
HTTP endpoint blocked by future-date guard (`period_end=2026-04-30 > 2026-04-16`) — service function used directly.

### Result

| OBP | OPA | Property | Opening | total_charges | Closing |
|---|---|---|---|---|---|
| 25686 | 1824 | Fallen Timber Lodge | $504,738.26 | **$169.00** | **$504,569.26** |
| 25687 | 1826 | Cherokee Sunrise | $64,822.71 | $0 | $64,822.71 |
| 25688 | 1827 | Serendipity | $308,517.68 | $0 | $308,517.68 |

- `created=3`, `skipped=0`, `errors=0` ✓
- FTL `total_charges=$169` — **I.4 OBP recompute end-to-end**: carpenter-bee charge 355 (2026-04-16) was picked up during generation. ✓
- Cherokee and Serendipity OBPs generated despite `stripe_account_id=NULL` ✓
- Opening balances = March closing balances (chained correctly) ✓

---

## 6. `pay_enabled` Field Validation

| OPA | status | stripe | pay_enabled | Expected |
|---|---|---|---|---|
| 1824 | pending_approval | set | **False** | False ✓ (not approved) |
| 1826 | pending_approval | NULL | **False** | False ✓ (no Stripe + not approved) |
| 1827 | pending_approval | NULL | **False** | False ✓ (no Stripe + not approved) |
| 1824 | (simulated approved) | set | **True** | True ✓ (Stripe + approved) |

Logic confirmed: `pay_enabled = bool(stripe_account_id AND status IN (approved, paid))`.

---

## 7. Confidence Rating

| Item | Confidence |
|---|---|
| Filter removed: all 3 OPAs generate OBPs | **CERTAIN** — 3 created, 0 errors in run |
| FTL April total_charges=$169 (carpenter-bee) | **CERTAIN** — DB shows $169 in OBP 25686 |
| Cherokee/Serendipity with stripe=NULL succeed | **CERTAIN** — OBPs 25687, 25688 created |
| pay_enabled=False for pending_approval | **CERTAIN** — validated via Python |
| pay_enabled=True for approved + Stripe | **CERTAIN** — simulated and confirmed |
| TypeScript zero errors | **CERTAIN** — tsc --noEmit clean |
| Build clean | **CERTAIN** — next build succeeded |
| March OBPs untouched | **CERTAIN** — 25680–25682 unchanged |

---

## 8. Recommended Next Phase

**I.5 — Pay Owner:** Real money out via Stripe Connect. The `pay_enabled` field created in H.2a is the gate condition for the Pay button. I.5 design must handle payout aggregation for secondary OPAs (Cherokee, Serendipity) — their statements are ready but their `stripe_account_id=NULL`. Options: route via OPA 1824's Stripe account with internal split tracking, or create per-property Stripe Express accounts.

**H.3 — Parity audit:** Compare CROG March 2026 PDFs vs NAS-archived Streamline PDFs line-by-line for Serendipity and Cherokee.
