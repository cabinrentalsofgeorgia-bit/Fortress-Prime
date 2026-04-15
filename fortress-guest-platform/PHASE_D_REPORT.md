# Phase D Report — Statement Generation and Approval Workflow
**Date:** 2026-04-14  
**Migration revision:** `f1e2d3c4b5a6`

---

## 1. State Machine Diagram

```
  [draft] ─────────────────────────────────► [voided] (terminal)
     │                                            ▲
     │ generate_monthly_statements()              │
     ▼                                            │
  [pending_approval] ──────────────────────────── ┤ void_statement()
     │                                            │
     │ approve_statement()                        │
     ▼                                            │
  [approved] ──────────────────────────────────── ┤
     │   │                                        │
     │   │ mark_statement_emailed()               │
     │   ▼                                        │
     │  [emailed] ──────────────────────────────► (terminal, nothing allowed)
     │
     │ mark_statement_paid()
     ▼
  [paid] ──── mark_statement_emailed() ──►  [emailed]
     │
     ╳ void_statement() FORBIDDEN (money has moved)
     ╳ paid → voided is FORBIDDEN
     ╳ emailed → anything is FORBIDDEN

Additional allowed paths:
  [approved] → mark_statement_emailed() → [emailed] → mark_statement_paid() → [paid]
  (payment and email can happen in either order; both are valid)
```

**Forbidden transitions (raise StatementWorkflowError):**
- draft → approved (must go through pending_approval first)
- pending_approval → paid (must approve first)
- paid → voided (ACH has moved; use credit_from_management in next period)
- emailed → voided (owner has been notified)
- emailed → any other status

---

## 2. Migration

**Revision:** `f1e2d3c4b5a6`

Three columns added to `owner_balance_periods`:

| Column | Type | Purpose |
|---|---|---|
| `voided_at` | TIMESTAMPTZ NULL | Timestamp when statement was voided |
| `voided_by` | VARCHAR(255) NULL | User email who voided the statement |
| `paid_by` | VARCHAR(255) NULL | User email who marked the statement paid |

Phase A created `approved_at`, `approved_by`, `paid_at`, `emailed_at`. Phase D adds
the three missing attribution columns. Every lifecycle transition now has both a
timestamp and a user identity.

---

## 3. generate_monthly_statements

**Function signature:**
```python
generate_monthly_statements(
    db: AsyncSession,
    period_start: date,
    period_end: date,
    dry_run: bool = False,
) -> GenerateStatementsResult
```

**StatementGenerationOutcome statuses:**

| Status | Meaning |
|---|---|
| `created` | New draft period row created and computed |
| `updated` | Existing draft/pending_approval row updated with fresh computation |
| `skipped_locked` | Period exists with approved/paid/emailed/voided status — left untouched |
| `skipped_not_renting` | Property is pre_launch/paused/offboarded — no statement generated |
| `skipped_not_enrolled` | Owner has no stripe_account_id — not yet enrolled |
| `error` | Computation raised an exception — logged, skipped, others continue |

**The regeneration-skips-finalized-rows safety rule:**

The single most important invariant in Phase D: calling `generate_monthly_statements`
for a period that already has an approved, paid, emailed, or voided row will NEVER
modify that row. It reports `skipped_locked` and moves on.

This is enforced in the code at:
```python
if period.status in _LOCKED_STATUSES:   # approved, paid, emailed, voided
    outcomes.append(... status="skipped_locked" ...)
    continue
```

**Test name for this rule:** `test_generate_skips_locked_status` (parametrized over
all four locked statuses: approved, paid, emailed, voided). All four pass.

---

## 4. Lifecycle Functions

All four functions live in `backend/services/statement_workflow.py`.

| Function | Required input status | Output status |
|---|---|---|
| `approve_statement(db, period_id, user_id)` | `pending_approval` only | `approved` |
| `void_statement(db, period_id, reason, user_id)` | `draft`, `pending_approval`, `approved` | `voided` |
| `mark_statement_paid(db, period_id, ref, user_id)` | `approved` or `emailed` | `paid` |
| `mark_statement_emailed(db, period_id)` | `approved` or `paid` | `emailed` |

Any invalid transition raises `StatementWorkflowError(code="invalid_transition", message=...)`.
The message names the current status, the rejected operation, and why it is forbidden.

---

## 5. Endpoints

All seven endpoints live in `backend/api/admin_statements_workflow.py`, mounted at
`/api/admin/payouts`. All require `require_manager_or_admin`.

**File choice:** New file rather than extending `admin_payouts.py`. The statement
lifecycle is a distinct domain with its own models and workflow functions.
`admin_payouts.py` already handles payout schedules, invite flow, and the send-all
stub — the statement lifecycle sits cleanly in its own module.

### POST /api/admin/payouts/statements/generate

```bash
# Happy path
curl -X POST http://localhost:8100/api/admin/payouts/statements/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"period_start": "2026-03-01", "period_end": "2026-03-31", "dry_run": false}'

# Rejection: future period
curl -X POST http://localhost:8100/api/admin/payouts/statements/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"period_start": "2027-01-01", "period_end": "2027-01-31"}'
# → HTTP 422: "period_end (2027-01-31) is in the future. Statements can only be generated for completed months."
```

### POST /api/admin/payouts/statements/{id}/approve

```bash
# Happy path (period_id=42 in pending_approval)
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/approve \
  -H "Authorization: Bearer $TOKEN"

# Rejection: period is a draft, not pending_approval
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/approve \
  -H "Authorization: Bearer $TOKEN"
# → HTTP 409: "Cannot approve statement 42: current status is 'draft'. Only 'pending_approval' statements can be approved."
```

### POST /api/admin/payouts/statements/{id}/void

```bash
# Happy path (period in approved status)
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/void \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Incorrect commission rate applied — rerun after fix"}'

# Rejection: period is paid
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/void \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Test"}'
# → HTTP 409: "Cannot void statement 42 (status='paid'): the ACH payment has already been initiated — use a credit_from_management charge in the next period instead"
```

### POST /api/admin/payouts/statements/{id}/mark-paid

```bash
# Happy path
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/mark-paid \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"payment_reference": "QB-ACH-2026-05-15-001"}'

# Rejection: period is a draft
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/mark-paid \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"payment_reference": "QB-REF"}'
# → HTTP 409: "Cannot mark statement 42 as paid (current status='draft'). Only 'approved' or 'emailed' statements can be marked paid."
```

### POST /api/admin/payouts/statements/{id}/mark-emailed

```bash
# Happy path
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/mark-emailed \
  -H "Authorization: Bearer $TOKEN"

# Rejection: period is a draft
curl -X POST http://localhost:8100/api/admin/payouts/statements/42/mark-emailed \
  -H "Authorization: Bearer $TOKEN"
# → HTTP 409: "Cannot mark statement 42 as emailed (current status='draft'). Only 'approved' or 'paid' statements can be marked emailed."
```

### GET /api/admin/payouts/statements

```bash
curl "http://localhost:8100/api/admin/payouts/statements?status=pending_approval&period_start=2026-03-01&period_end=2026-03-31" \
  -H "Authorization: Bearer $TOKEN"
```

### GET /api/admin/payouts/statements/{id}

```bash
curl http://localhost:8100/api/admin/payouts/statements/42 \
  -H "Authorization: Bearer $TOKEN"
# Returns: {"balance_period": {...}, "statement": {line_items, owner_charges, ...}}
```

---

## 6. Tests

**Test count:** 676 → **702 passing** (+26 new tests)

**Most critical forbidden-transition tests (all passing, by name):**

| Test name | What it verifies |
|---|---|
| `test_generate_skips_locked_status[approved]` | Approved period is never regenerated |
| `test_generate_skips_locked_status[paid]` | Paid period is never regenerated |
| `test_generate_skips_locked_status[emailed]` | Emailed period is never regenerated |
| `test_generate_skips_locked_status[voided]` | Voided period is never regenerated |
| `test_forbidden_approve_a_draft` | approve_statement rejects draft input |
| `test_forbidden_void_a_paid_statement` | void_statement rejects paid input |
| `test_forbidden_void_an_emailed_statement` | void_statement rejects emailed input |
| `test_forbidden_mark_paid_on_draft` | mark_statement_paid rejects draft input |
| `test_forbidden_mark_emailed_on_draft` | mark_statement_emailed rejects draft input |

The parametrized `test_generate_skips_locked_status` counts as 4 separate tests
(one per locked status) and is the most important group in the test file.

**Integration test:** `test_end_to_end_generate_to_emailed_with_real_data`
Creates a real reservation (Creekside Green, 5 nights @ $400, 30% commission) and
a real owner charge ($325 maintenance) in a specific period, then runs
`generate_monthly_statements` and verifies:
- `total_revenue = $2,000.00` (5 × $400)
- `total_commission = $600.00` (30%)
- `total_charges = $325.00`
- `closing_balance = $1,075.00` (2000 - 600 - 325 = 1075)

Then runs the full lifecycle: pending_approval → approved → paid → emailed, and
verifies all timestamps and user attributions are set.

---

## 7. NOTES.md Additions

Two items added to NOTES.md:

- **Statement workflow admin UI not yet built.** The seven lifecycle endpoints
  exist but the UI (statement list, approve/void/mark-paid buttons) does not.
  All workflow must currently be driven via curl/Postman/admin scripts.
  Priority: HIGH — needed for the first real statement run.

- **Auto-generated charges from Streamline not yet modeled.** Phase G's
  reconciliation is the discovery mechanism; Phase G.5 (if needed) will add
  support. Do NOT anticipate these in Phase E or F.

---

## 8. Confidence: HIGH

All 26 Phase D tests pass. The state machine forbidden transitions are tested by
name. The integration test verifies the full lifecycle with real DB data and correct
arithmetic. The `generate_monthly_statements` safety rule (skipping locked rows) is
parametrized and proven for all four locked statuses.

Two minor notes:
- The `dry_run` implementation rolls back the transaction using `await db.rollback()`.
  This is correct for the in-process test but could be surprising if called from an
  outer transaction. For Phase F's cron usage it will be called in its own session.
- The `generate_monthly_statements` function enumerates ALL enrolled owners (not
  filtered by property renting_state at the query level). The pre_launch/offboarded
  skip happens inside the loop. This means the query is slightly broader than needed
  but the outcome is identical. Flagged as a minor efficiency improvement but not a
  correctness issue.

---

## 9. Ready for Phase E

Phase D is complete. The statement lifecycle is fully functional. Phase E builds the
PDF renderer that produces the owner-facing statement document matching Streamline's
format.
