# Phase A Report — Owner Ledger Foundation
**Date:** 2026-04-14  
**Migration revision:** `d1e2f3a4b5c6`

---

## What was built

### A1 — Property renting state

A new column `renting_state` was added to the `properties` table with four possible
values: `active`, `pre_launch`, `paused`, `offboarded`. It is NOT NULL with a default
of `active`, so all 58 existing properties were automatically backfilled to `active`.
Restoration Luxury was immediately updated to `pre_launch` by the migration itself —
the migration raises an error if it cannot find the property by name, which protects
against the migration silently doing nothing if the property was renamed.

The `Property` SQLAlchemy model was updated to include `renting_state` as a mapped
column.

**What this means in practice:** Restoration Luxury can never generate an owner
statement as long as its `renting_state` is `pre_launch`. When it begins renting,
an admin changes `renting_state` to `active` and statements will include it
from that point forward.

### A2 — Owner balance periods table

The `owner_balance_periods` table was created. It stores one row per owner per
calendar period and serves as the official record of what each owner is owed.

The table enforces the accounting ledger equation at the database level via a CHECK
constraint. If any code tries to write a row where the numbers don't add up —
for example, setting `closing_balance` to $1,000 when the math says it should be
$800 — the database rejects the INSERT or UPDATE immediately. This catches
accounting bugs at the data layer rather than silently persisting wrong numbers.

The `status` column tracks the statement's lifecycle:
`draft` → `pending_approval` → `approved` → `paid` → `emailed`
with `voided` available as an exit from most states.

The `OwnerBalancePeriod` SQLAlchemy model and `StatementPeriodStatus` Python enum
were created in `backend/models/owner_balance_period.py`.

### A3 — Balance carry-forward function

`get_or_create_balance_period(db, owner_payout_account_id, period_start, period_end)`
was built in `backend/services/balance_period.py`.

Calling this function for an owner+period:
- **If the row already exists:** returns it unchanged (idempotent)
- **If no row exists:** creates a new `draft` row, with `opening_balance` equal to
  the `closing_balance` of the most recent prior period for that owner
- **If no prior period exists:** opening_balance = $0.00

The function uses `SELECT FOR UPDATE` to prevent duplicate rows if two processes
call it simultaneously for the same owner and period.

### A4 — Renting-state guard in compute_owner_statement

`compute_owner_statement` now raises `StatementComputationError(code='property_not_renting')`
before doing any computation if the property's `renting_state` is not `active`.
This means calling the function for Restoration Luxury (or any future paused/offboarded
property) returns a clear error with the property name and its current state, rather
than returning a misleading empty statement.

---

## Test count delta

| Metric | Before Phase A | After Phase A |
|---|---|---|
| Total passing | 606 | **617** |
| New tests (Phase A file) | — | **11** |
| Failing | 1 (pre-existing) | 1 (pre-existing, unchanged) |

All 11 Phase A tests pass. Every item in the Phase A spec was tested:
- Migration count checks (1 pre-launch, 13 active)
- Column non-nullability
- Restoration Luxury specifically set to pre_launch
- Table structure verification
- Ledger equation CHECK constraint rejects bad rows
- `get_or_create_balance_period` with zero opening balance
- `get_or_create_balance_period` with prior period carry-forward
- `get_or_create_balance_period` is idempotent
- `compute_owner_statement` raises `property_not_renting` for Restoration Luxury
- `compute_owner_statement` succeeds for an active property

---

## Items flagged for NOTES.md

**1. Skyfall has 0 reservations in the past 12 months despite being `is_active = true`.**
The discovery query showed Skyfall with no confirmed reservations. This may be intentional
(property was recently added or paused informally), or it may need investigation.
Since `renting_state` now exists, consider whether Skyfall's state should be `paused`
rather than `active`. Flagged for the product owner to decide; no code change made.

**2. The `owner_balance_periods` CHECK constraint cannot be bypassed by code.**
Any service function that updates totals on a period row must recompute `closing_balance`
before writing. The formula is:
`closing = opening + revenue - commission - charges - payments + owner_income`.
Phase D's `generate_monthly_statements()` must maintain this invariant.

---

## Confidence: HIGH

The migration ran cleanly, all constraints were verified against the live database,
and all 11 tests pass. The `renting_state` guard in `compute_owner_statement` was
tested against real data (the actual Restoration Luxury property). The
`get_or_create_balance_period` carry-forward logic was tested with a real prior period
row that was manually constructed in the test.

---

## Ready for Phase B

There are no blockers for Phase B. The Phase A work is complete and clean.

Phase B will:
- Remove the CC processing fee deduction from `calculate_owner_payout`
- Add `is_owner_booking` column to reservations
- Backfill the 5 confirmed + up to 5 cancelled owner bookings
- Fix the 5 lump-sum Streamline reservations (nightly_rate = 0)
- Add multi-month reservation splitting
- Exclude owner bookings from `compute_owner_statement`
