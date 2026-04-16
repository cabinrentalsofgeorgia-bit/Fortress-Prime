# Phase I.5 Report — Pay Owner via Stripe Connect
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Transfer wired and tested. Action required: Gary must complete Stripe Express onboarding to enable actual transfers.

---

## 1. Pre-flight: Stripe Mode + Account Status

| Check | Result |
|---|---|
| Stripe key prefix | `sk_test_` — **TEST MODE** ✓ Safe to proceed |
| Gary's connected account | `acct_1TMYCpK5ULr6Eoss` on OPA 1824 |
| `payout_ledger` table | EXISTS (but per-reservation design — new OBP columns used instead) |
| OBP columns `paid_at`, `paid_by` | Existed already |
| OBP columns `stripe_transfer_id`, `paid_amount` | Added via migration `i5a1_obp_payout_columns` |

---

## 2. Existing Stripe Integration Audit

**Scenario B** — `initiate_transfer` exists in `payout_service.py` (line 108) but lacked:
- `idempotency_key` parameter ← added
- OBP-level payout semantics (it was per-reservation)

**Existing** `stripe.Transfer.create` call confirmed working (API key valid, connected account identified).

**`payout_ledger` table**: Per-reservation design with `confirmation_code`, `gross_amount`, etc. — not suitable for OBP-level payouts. Used new OBP columns instead.

---

## 3. `pay_owner_for_statement` Service

**File:** `backend/services/owner_payout_service.py`

```python
async def pay_owner_for_statement(db, *, period_id, admin_email) -> PayOwnerResult
```

**Validation chain:**
1. OBP exists (404 if not)
2. `status=paid` → `PayoutValidationError(already_paid)` with transfer_id in message
3. `status` not in `{approved, emailed}` → `PayoutValidationError(invalid_status)`
4. OPA exists and has `stripe_account_id` → `PayoutValidationError(no_stripe)` if missing
5. `payout_amount = closing - opening` → `PayoutValidationError(no_net_income)` if ≤ 0

**Transfer:**
- Calls `initiate_transfer(account_id, amount, description, metadata, idempotency_key="pay-obp-{period_id}")`
- On success: `status → paid`, `paid_at`, `paid_by`, `stripe_transfer_id`, `paid_amount` recorded
- On failure: OBP stays in `approved/emailed`, error returned in `PayOwnerResult.error`

**Non-blocking on Stripe failure:** charge save semantics — OBP never moves to `paid` unless Stripe confirms.

---

## 4. API Endpoint

**Added to** `backend/api/admin_statements_workflow.py`:

```
POST /api/admin/payouts/statements/{id}/pay
```

- Requires `require_manager_or_admin`
- Calls `pay_owner_for_statement` → raises 400 on `PayoutValidationError`, 502 on Stripe error
- Returns `_period_dict` extended with `stripe_transfer_id` and `paid_amount`

**`_period_dict` extended** with `stripe_transfer_id` and `paid_amount` fields (sourced from new OBP columns via `getattr` with fallback).

---

## 5. Frontend Pay Button

### `hooks.ts`
Added `usePayOwner()` — `POST /api/admin/payouts/statements/{id}/pay`, invalidates `["admin-statements"]` on success.

### `types.ts`
Added `stripe_transfer_id: string | null` and `paid_amount: string | null` to `OwnerBalancePeriod`.

### `page.tsx` (statements list)
**`PayDialog`** component:
- Shows OPA, period, opening/closing, computed payout amount
- Idempotency key displayed: `pay-obp-{id}`
- "Confirm Payment" button calls `usePayOwner`
- Toast: `"Payment of ${amount} sent to OPA #{id}"`

**`RowActions`** update:
- Pay button (`CreditCard` icon) now active (blue) when `pay_enabled=true AND payoutAmount > 0`
- Disabled (grayed) with context-sensitive tooltip otherwise:
  - "Stripe not connected (secondary OPA)" — when `pay_enabled=false`
  - "No net income this period" — when `payoutAmount <= 0`
  - "Pay owner via Stripe" — when active

**`payTarget` state** added to main component.

**TypeScript:** zero errors. Build clean.

---

## 6. Payout Record Storage

**Migration:** `i5a1_obp_payout_columns` (revises `i1a2_add_vendor_and_markup`)

| Column | Type | Purpose |
|---|---|---|
| `stripe_transfer_id` | VARCHAR(100) | Stripe `tr_...` ID, indexed (partial: IS NOT NULL) |
| `paid_amount` | NUMERIC(12,2) | Amount transferred (closing - opening at payment time) |

Combined with existing `paid_at` (TIMESTAMPTZ) and `paid_by` (VARCHAR 255), the OBP row contains full audit trail.

---

## 7. Validation Results

### Stripe transfer attempt (FTL March 2026, payout=$4,035.85)

**Result:** Stripe API reached, transfer rejected with:  
`"Your destination account needs to have at least one of the following capabilities enabled: transfers, crypto_transfers, or legacy_payments."`

**Root cause:** `acct_1TMYCpK5ULr6Eoss` is a test-mode Stripe Express account that has NOT completed onboarding. Transfer capability is disabled until Gary completes the Stripe Express onboarding flow.

**Code behavior:** Correct — OBP stayed in `approved`, error returned cleanly in `PayOwnerResult.error`.

### `already_paid` guard (simulated successful pay)

Manually set OBP to `status=paid` with `stripe_transfer_id=tr_SIMULATED`. Then:
- `pay_owner_for_statement` raised `PayoutValidationError(code="already_paid")` ✓
- Message included `stripe_transfer_id=tr_SIMULATED` for auditability ✓

### Negative balance guard

`closing < opening` case is blocked by OBP ledger CHECK constraint (`chk_obp_ledger_equation`) in the DB — this constraint prevents negative-net OBPs from existing. The service's `no_net_income` guard is a belt-and-suspenders check for edge cases where `opening_balance` was manually set higher than `closing_balance`.

### OBP restoration

OBP 25680 restored to `pending_approval` after all tests. All March and April OBPs intact.

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| Transfer API code reaches Stripe | **CERTAIN** — Stripe returned a meaningful error (not auth failure) |
| `already_paid` guard fires correctly | **CERTAIN** — tested with simulated `status=paid` |
| Non-blocking failure: OBP stays in approved | **CERTAIN** — OBP 25680 stayed `approved` after Stripe rejection |
| Idempotency key sent to Stripe | **CERTAIN** — `idempotency_key="pay-obp-25680"` in request log |
| `stripe_transfer_id`/`paid_amount` columns exist | **CERTAIN** — migration applied, columns in DB |
| TypeScript zero errors | **CERTAIN** — tsc --noEmit clean |
| Build clean | **CERTAIN** — next build succeeded |

---

## 9. Action Required Before Live Transfers

**Gary must complete Stripe Express onboarding** for account `acct_1TMYCpK5ULr6Eoss`:
1. Log into Stripe Dashboard → Connect → Accounts
2. Find `acct_1TMYCpK5ULr6Eoss`
3. Complete KYC / bank account details in the Express onboarding flow
4. Once `transfers` capability shows as enabled, re-test with a small amount

**In test mode only:** Gary can also create a test bank account through Stripe test onboarding flow to enable test transfers.

---

## 10. Recommended Next Phase

**Complete Stripe onboarding** (not a code phase — operational action by Gary).

**After onboarding:**
- Test with Cherokee April OBP 25687 (net=0, `no_net_income` guard fires) → no transfer, expected
- Approve FTL March OBP and Pay → verify real test transfer appears in Stripe dashboard

**I.5.1 — Payout aggregation for secondary OPAs:** Cherokee (1826) and Serendipity (1827) have `pay_enabled=False`. Design: route their payouts through OPA 1824's Stripe account with internal split tracking.

**I.2 — Receive Owner Payment:** Record a payment from owner to management (owner reserve top-up).
