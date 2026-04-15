# Phase C Report — Owner Charges Table, Admin Endpoints, Statement Integration
**Date:** 2026-04-14  
**Migration revision:** `c9e2f4a7b1d3`

---

## 1. Migration

Revision `c9e2f4a7b1d3` creates:

### Database enum `owner_charge_type_enum`
17 values (all lowercase with underscores):
`cleaning_fee`, `maintenance`, `management_fee`, `supplies`, `landscaping`,
`linen`, `electric_bill`, `housekeeper_pay`, `advertising_fee`,
`third_party_ota_commission`, `travel_agent_fee`, `credit_card_dispute`,
`federal_tax_withholding`, `adjust_owner_revenue`, `credit_from_management`,
`pay_to_old_owner`, `misc_guest_charges`

### Table `owner_charges`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | auto-increment |
| `owner_payout_account_id` | BIGINT FK → owner_payout_accounts | ON DELETE RESTRICT |
| `posting_date` | DATE NOT NULL | |
| `transaction_type` | owner_charge_type_enum NOT NULL | |
| `description` | VARCHAR(500) NOT NULL | empty string rejected by CHECK |
| `amount` | NUMERIC(12,2) NOT NULL | zero rejected by CHECK |
| `reference_id` | VARCHAR(100) NULL | optional work order ref or invoice # |
| `originating_work_order_id` | BIGINT NULL | optional link to work_orders table |
| `created_at` | TIMESTAMPTZ DEFAULT now() | |
| `created_by` | VARCHAR(255) NOT NULL | staff email from JWT |
| `voided_at` | TIMESTAMPTZ NULL | must be set with voided_by |
| `voided_by` | VARCHAR(255) NULL | must be set with voided_at |
| `void_reason` | TEXT NULL | |

Three CHECK constraints:
- `chk_oc_amount_not_zero` — amount ≠ 0
- `chk_oc_description_not_empty` — description ≠ ''
- `chk_oc_void_pair` — voided_at and voided_by must be set together or not at all

Three indexes, including a partial index on active (non-voided) charges for
fast period lookups.

---

## 2. Endpoint Summary

All endpoints live at `backend/api/admin_charges.py` and are mounted at
`/api/admin/payouts`. They require `require_manager_or_admin`.

**Decision:** A new file `admin_charges.py` was created rather than extending
`admin_payouts.py`. Rationale: `admin_payouts.py` is already 386 lines handling
payout schedules, ledger sweeps, invites, and statements. Charges are a
distinct workflow and benefit from their own module. Both files are mounted at
the same prefix `/api/admin/payouts`, so the URL namespace is unified.

### POST /api/admin/payouts/charges — Create a charge
```bash
curl -X POST http://localhost:8100/api/admin/payouts/charges \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "owner_payout_account_id": 42,
    "posting_date": "2026-03-15",
    "transaction_type": "maintenance",
    "description": "Hot tub pump replacement",
    "amount": 325.00,
    "reference_id": "INV-2026-0312"
  }'
```
Validates: enrolled owner, active/pre_launch property, period not locked, non-zero
amount, non-empty description. Returns the created charge. `created_by` is set from
the authenticated user's email.

### GET /api/admin/payouts/charges — List charges
```bash
curl "http://localhost:8100/api/admin/payouts/charges?owner_payout_account_id=42&period_start=2026-03-01&period_end=2026-03-31" \
  -H "Authorization: Bearer $TOKEN"
```
Voided charges excluded by default. Add `include_voided=true` to include them.

### GET /api/admin/payouts/charges/{id} — Get one charge
```bash
curl http://localhost:8100/api/admin/payouts/charges/17 \
  -H "Authorization: Bearer $TOKEN"
```

### PATCH /api/admin/payouts/charges/{id} — Update a charge
```bash
curl -X PATCH http://localhost:8100/api/admin/payouts/charges/17 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Corrected: hot tub pump + labor", "amount": 425.00}'
```
Rejected if the charge is voided or if its posting_date (current or new) falls in
a locked period. Returns HTTP 409 with the period dates and current status.

### POST /api/admin/payouts/charges/{id}/void — Void a charge
```bash
curl -X POST http://localhost:8100/api/admin/payouts/charges/17/void \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"void_reason": "Entered against wrong property. See charge #18."}'
```
Rejected if already voided or if the period is locked (HTTP 409). Soft-delete only
— the row is never removed.

---

## 3. Approval Lock

### How `is_charge_period_locked()` works

```python
async def is_charge_period_locked(db, owner_payout_account_id, posting_date) -> OwnerBalancePeriod | None
```

Queries `owner_balance_periods` for a row where:
- `owner_payout_account_id` matches
- `period_start <= posting_date <= period_end`
- `status IN ('approved', 'paid', 'emailed', 'voided')`

Returns the matching period row (truthy) if locked, `None` if not.

**Locked statuses:** `approved`, `paid`, `emailed`, `voided`. The `draft` and
`pending_approval` statuses are NOT locked — charges in those periods can still
be modified.

**Error message to users (HTTP 409):**
```
Cannot modify charge: the statement period 2026-03-01 to 2026-03-31 is already
'approved'. Use a credit_from_management entry in a later period to correct
this charge.
```

The message names the exact period dates and status so staff know which statement
to look at.

---

## 4. compute_owner_statement Integration

`StatementResult` now includes two new fields:

```python
owner_charges: list[OwnerChargeLineItem]   # all non-voided charges in the period
total_charges: Decimal                      # sum of amounts (+ve charges, -ve credits)
```

Where `OwnerChargeLineItem` has:
- `posting_date`, `transaction_type`, `transaction_type_display`, `description`,
  `amount`, `reference_id`

The charges query filters:
- `owner_payout_account_id = :id`
- `posting_date >= period_start AND posting_date <= period_end`
- `voided_at IS NULL`

**Ledger equation check:** When `owner_balance_periods` rows are computed
and saved (Phase D), `total_charges` feeds into the ledger equation:
```
closing_balance = opening_balance + total_revenue - total_commission
                  - total_charges - total_payments + total_owner_income
```
The CHECK constraint `chk_obp_ledger_equation` on `owner_balance_periods` will
reject any write where this doesn't hold, providing a database-level correctness
guarantee.

---

## 5. Test Count Delta

| Metric | Before Phase C | After Phase C |
|---|---|---|
| Total passing | 645 | **676** |
| New Phase C tests | — | **31** (test_phase_c_owner_charges.py) |
| Failing | 1 (pre-existing) | 1 (pre-existing, unchanged) |

---

## 6. Confidence: HIGH

All 31 Phase C tests pass. The approval lock was tested with all four locked
statuses (approved, paid, emailed, voided) and confirmed it returns None for
`draft`. The state machine integration test creates a charge in an open period,
approves the period, then confirms that create/patch/void all return 409 — and
that creating a charge in a different open period still succeeds.

The `owner_balance_periods` CHECK constraint was verified in Phase A. Charges
slot cleanly into the ledger equation. No regression in the prior 645 tests.

---

## 7. NOTES.md Additions

The following items were added to NOTES.md (created in this phase):

- **Owner Charges admin UI form not yet built** — backend endpoints exist,
  frontend form is a follow-up task. Staff must use curl or Postman until the
  form is built. Priority: HIGH before real charges can be entered through the UI.

- **Owner charge transaction types are a starter set** — 17 values, 4 excluded.
  Add new types only via migration when a real workflow requires them.

- **Owner Reserve sub-account** — not yet implemented; Phase E PDF will show $0.

- All other NOTES.md items were carried over from prior sessions.

---

## 8. Ready for Phase D

Phase D builds statement generation (`generate_monthly_statements()`), the
approval workflow (`approve_statement`, `void_statement`, `mark_statement_paid`,
`mark_statement_emailed`), status transitions, and the admin endpoints for the
statement lifecycle.

Phase C's foundation — the `owner_charges` table, the `is_charge_period_locked()`
helper, and the `total_charges` field in `StatementResult` — is exactly what
Phase D's `generate_monthly_statements()` needs to populate `owner_balance_periods`
with correct totals.
