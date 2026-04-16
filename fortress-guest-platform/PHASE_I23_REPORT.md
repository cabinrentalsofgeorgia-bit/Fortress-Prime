# PHASE I.2/I.3 REPORT — Receive Owner Payment + Credit Owner Account

**Date:** 2026-04-16  
**Branch:** feature/owner-statements-and-stabilization  
**Base commit:** 1988346b5 (phase I.5: Pay Owner via Stripe Connect)

---

## 1. Pre-flight Verification

| Check | Result |
|---|---|
| Branch | `feature/owner-statements-and-stabilization` ✓ |
| Latest commit | `1988346b5 phase I.5: Pay Owner via Stripe Connect` ✓ |
| `fortress-backend.service` | active ✓ |
| `crog-ai-frontend.service` | active ✓ |
| OBP 25680 | `total_charges=0.00`, `closing_balance=504738.26`, `pending_approval` ✓ |
| Backend port | `:8000` (not :8100 as in phase spec — correct) |

---

## 2. Transaction Codes: Existing vs Added

### Existing (no change needed for I.3 Credit Account)
- `credit_from_management` — "Credit From Management" ✓ pre-existing
- `adjust_owner_revenue` — "Adjust Owner Revenue" ✓ pre-existing

### Added for I.2 (Receive Payment)
- `owner_payment_received` — "Owner Payment Received" **NEW**
  - Migration: `i23a1_add_payment_credit_codes` (revises `i5a1_obp_payout_columns`)
  - `ALTER TYPE owner_charge_type_enum ADD VALUE IF NOT EXISTS 'owner_payment_received'`
  - Migration applied successfully. DB enum now has 22 values (was 21).

### Frontend categorization sets added (`owner-charge-codes.ts`)
- `PAYMENT_CODES: ReadonlySet<string>` = `{"owner_payment_received"}`
- `CREDIT_CODES: ReadonlySet<string>` = `{"credit_from_management", "adjust_owner_revenue"}`

---

## 3. Backend Amount Validation

**No changes required.**

`backend/api/admin_charges.py` already uses:
```python
@field_validator("amount")
def _amount_not_zero(cls, v):
    if v is not None and v == Decimal("0"):
        raise ValueError("amount must not be zero")
    return v
```

`amount != 0` — negative amounts were already accepted. The DB model docstring
(added I.1) explicitly states: "Negative amount = credit to owner (increases
owner balance)."

`vendor_amount` remains positive-only — this is correct since it represents
the raw vendor invoice amount, not the sign-bearing owner charge.

---

## 4. Frontend UI Enhancements

**File:** `apps/command-center/src/app/(dashboard)/admin/owner-charges/page.tsx`

### New types
- `ModalMode = "charge" | "payment" | "credit"` — controls modal behavior
- `TypeFilter = "all" | "charges" | "payments" | "credits"` — client-side table filter

### Three action buttons (header)
| Button | Icon | Behavior |
|---|---|---|
| Post Charge | PlusCircle | All codes; amount field accepts + or − |
| Receive Payment | ArrowDownCircle (green) | Only PAYMENT_CODES; user enters positive, stored as negative |
| Credit Account | CreditCard (blue) | Only CREDIT_CODES; user enters positive, stored as negative |

### MODE_CONFIG per mode
Each mode has: `title`, `amountLabel`, `amountHint`, `descPlaceholder`, `defaultCode` (pre-selected).

- Payment → defaultCode: `owner_payment_received`
- Credit → defaultCode: `credit_from_management`

### Amount sign handling
```typescript
const finalAmount =
  (mode === "payment" || mode === "credit") && !showVendor
    ? -Math.abs(rawAmount)
    : rawAmount;
```

### Type filter (client-side)
```
All → all charges
Charges → parseFloat(amount) > 0
Payments → amount < 0 AND PAYMENT_CODES.has(transaction_type)
Credits → amount < 0 AND CREDIT_CODES.has(transaction_type)
```

### Amount display
- Negative amounts: green `(${abs})` format via updated `fmtCurrency()`
- PMT/CR badge on negative rows in transaction type column
- Broken `transaction_type` filter replaced with `TypeFilter` dropdown

### Modal remount strategy
`key={modalMode ?? "closed"}` forces React remount when mode changes, ensuring
`useState` reinitializes with the correct `defaultCode` per mode. No `useEffect`
dependency array needed.

### Vendor section
Available in all three modes (charge, payment, credit). A payment from owner
may reference a vendor invoice. Collapsible and optional.

### TypeScript
`npx tsc --noEmit` → zero errors.

---

## 5. PDF Rendering for Negative Amounts

**File:** `backend/services/statement_pdf.py`

### Charge routing logic added to `_build_pdf_bytes()`

```python
pos_charges = [ch for ch in stmt.owner_charges if ch.amount > Decimal("0")]
neg_charges = [ch for ch in stmt.owner_charges if ch.amount < Decimal("0")]
pos_total = sum((ch.amount for ch in pos_charges), Decimal("0.00"))
neg_total_abs = sum((abs(ch.amount) for ch in neg_charges), Decimal("0.00"))
```

**Section 5 — "Owner Payments / Additional Owner Income":**  
- Now renders all negative-amount `owner_charges` as individual line items (displayed as positive)  
- Total = `owner_inc + neg_total_abs` (future owner_income + current payment/credit amounts)

**Section 6 — "Owner Charges/Expenses":**  
- Now renders only positive-amount `owner_charges`  
- Total = `pos_total` (unchanged rendering, just filtered)

**Account Summary:** Unchanged — still shows `total_charges` (net of all charges) under
"Owner Charges/Expenses". When credits exceed charges, this line shows a positive amount
increasing `Total Balance Due`. Math is correct; label is an acceptable approximation for
mixed-sign situations (out of scope for I.2/I.3 to redesign the summary).

---

## 6. End-to-End Validation

**Baseline OBP 25680:** `total_charges=0.00`, `closing_balance=504738.26`

### Scenario 1 — Receive Payment on FTL March
```
POST /api/admin/payouts/charges
{
  "owner_payout_account_id": 1824,
  "transaction_type": "owner_payment_received",
  "amount": -200.00,
  "posting_date": "2026-03-20"
}
```
Result (charge id=362):  
- `amount: -200.00` ✓  
- `obp_recomputed.old_closing: 504738.26` → `new_closing: 504938.26` (+$200) ✓  
- `new_total_charges: -200.00` ✓

### Scenario 2 — Credit Account on FTL March
```
POST /api/admin/payouts/charges
{
  "owner_payout_account_id": 1824,
  "transaction_type": "credit_from_management",
  "amount": -50.00,
  "posting_date": "2026-03-21"
}
```
Result (charge id=363):  
- `amount: -50.00` ✓  
- `obp_recomputed.old_closing: 504938.26` → `new_closing: 504988.26` (+$50) ✓  
- `new_total_charges: -250.00` ✓

### Scenario 3 — PDF Rendering
Generated `/api/admin/payouts/statements/25680/pdf` (5331 bytes):

Section 5 "Owner Payments / Additional Owner Income":
- "I.2 validation — owner payment received … $200.00" ✓
- "I.3 validation — account credit … $50.00" ✓  
- TOTAL: $250.00 ✓

Section 6 "Owner Charges/Expenses":
- Empty (no positive charges exist) ✓

### Scenario 4 — Void Both Test Entries
- Void charge 362: OBP `504988.26 → 504788.26` (delta -$200.00) ✓
- Void charge 363: OBP `504788.26 → 504738.26` (delta -$50.00) ✓  
- **OBP fully restored to baseline:** `total_charges=0.00`, `closing_balance=504738.26` ✓

---

## 7. Confidence Rating

**9/10**

All scenarios passed end-to-end. TypeScript zero errors. Build clean. Math
correct throughout. The Account Summary label ("Owner Charges/Expenses") for
purely-negative total_charges situations is cosmetically imprecise but
mathematically correct — deferred to a future phase (label cleanup is cosmetic,
not a correctness issue). No regressions observed in existing charge flows.

---

## 8. Recommended Next Phase

**J.1 — Recurring Charges**  
Scheduled owner charges (monthly management fees, advertising fees) that auto-post
on the first of each month. Would use the arq worker + new `recurring_charge_rules`
table. Deferred from I.2/I.3 scope per phase specification.

**Alternative: I.6 — Statement PDF polish**  
Fix the Account Summary label ambiguity for mixed-sign total_charges. Separate
"Owner Charges/Expenses" and "Owner Payments" rows in the Account Summary to
match Streamline exactly.
