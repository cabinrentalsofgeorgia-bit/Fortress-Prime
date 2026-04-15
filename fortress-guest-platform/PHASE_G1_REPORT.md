# Phase G.1 — Test Data Cleanup Report
**Date:** 2026-04-15  
**Database:** fortress_guest (PostgreSQL 16.13, localhost:5432)  
**User:** fgp_app  
**Type:** Read-only discovery + dry-run only. No data was modified.  
**Script:** `backend/scripts/g1_cleanup_test_statement_data.sql`  
**Dry-run log:** `backend/scripts/g1_cleanup_dryrun.log`

---

## Executive Summary

**Phase G.1 cleanup is a no-op. There is zero test data to remove.**

The pre-phase assumption — that test fixture rows had accumulated in the owner statement tables — is false. The actual situation is more significant: **three of the four Phase A-F workflow tables do not yet exist in the database** because the Alembic migrations were never applied. The tables that do exist are either empty or contain only real production data that must be preserved.

The actual blocker for Phase G.2 is not data cleanup. It is that `alembic upgrade head` needs to be run to create `owner_balance_periods`, `owner_charges`, and `owner_statement_sends`, and to add the `commission_rate` and `streamline_owner_id` columns to `owner_payout_accounts`.

---

## 1. Inventory Before

### Tables in scope — actual state

| Table | Exists? | Row Count | Notes |
|---|---|---|---|
| `owner_balance_periods` | **NO** | — | Phase A migration not applied |
| `owner_charges` | **NO** | — | Phase C migration not applied |
| `owner_statement_sends` | **NO** | — | Phase E migration not applied |
| `owner_payout_accounts` | Yes | **0** | Exists but empty; missing `commission_rate`, `streamline_owner_id` columns (Phase A-F not applied) |
| `owner_magic_tokens` | Yes | **7** | All belong to one real owner (sl_owner_id=897648) |
| `owner_statements` (legacy) | Yes | **0** | Pre-Phase-A legacy table; empty |
| `owner_statement_archive` | Yes | **9** | Streamline-imported PDFs; all real production data |
| `payout_ledger` | Yes | **0** | Stripe Connect payout ledger; empty |
| `properties` | Yes | **14** | All 14 active properties; none offboarded |
| `reservations` | Yes | **2,665** | Real guest bookings; not touched by this phase |

### Columns on owner_payout_accounts (current schema — pre-Phase-A)
```
id, property_id, owner_name, owner_email, stripe_account_id,
account_status, instant_payout, created_at, updated_at
```
**Missing** (added by Phase A migration, not yet applied):
- `commission_rate NUMERIC(5,4) NOT NULL`
- `streamline_owner_id INTEGER NULL`

### Applied Alembic version
```
c4a8f1e2b9d0  — reservation holds and overlap exclusion constraints
```
The Phase A-F migrations are unapplied files in `backend/alembic/versions/`.

---

## 2. Test vs Real Breakdown

### owner_payout_accounts (0 rows)

| Predicate | Count |
|---|---|
| email LIKE test/example domain | 0 |
| name contains Test/Fixture | 0 |
| Orphaned (no active property) | 0 |
| **Total test rows** | **0** |
| **Real rows** | **0** |

Note: The migration file `e7c3f9a1b5d2_owner_statement_infrastructure.py` documents that it deletes test rows before adding the `commission_rate NOT NULL` column — specifically rows `id=1` (test-accept-...@example.com) and `id=10` (test-e2e-...@example.com). Those rows no longer exist; the table is already empty.

### owner_magic_tokens (7 rows)

| Predicate | Count |
|---|---|
| email LIKE test/example domain | 0 |
| Expired AND unused AND no sl_owner_id | 0 |
| **Total test rows** | **0** |
| **Real rows** | **7** |

All 7 tokens belong to a single real owner attempting portal onboarding:
- Email: `mkbuquoi0912@gmail.com`
- Streamline owner ID: `897648` (valid numeric Streamline ID)
- All created 2026-03-01 during a login flow that generated multiple tokens
- 4 of 7 were used (`used_at` is set); 3 expired unused
- All are now expired (`expires_at` was 2026-03-02)
- This owner never completed onboarding — no row exists in `owner_payout_accounts`

### owner_statement_archive (9 rows)

| Streamline owner IDs present | Count |
|---|---|
| sl_owner_id = 897648 | 3 rows (statements for Nov 2025, Dec 2025, Jan 2026) |
| sl_owner_id = 451821 | 1 row |
| sl_owner_id = 920014 | 1 row |
| sl_owner_id = 385151 | 1 row |
| sl_owner_id = 416418 | 1 row |
| sl_owner_id = 503499 | 1 row |
| sl_owner_id = 146514 | 1 row |
| **Total real rows** | **9** |

All rows have real Streamline IDs and real PDF paths on `/mnt/fortress_nas/`. Period dates are historical (Nov 2025 – Jan 2026). These are real archived statements, not test data.

### Tables with 0 rows (nothing to evaluate)
`owner_balance_periods` (missing), `owner_charges` (missing), `owner_statement_sends` (missing), `owner_statements` (legacy), `payout_ledger`.

---

## 3. Dependency Graph (FK Relationships)

Query run:
```sql
SELECT tc.table_name, kcu.column_name, ccu.table_name AS parent, ...
FROM information_schema.table_constraints tc ...
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND (tc.table_name IN (...) OR ccu.table_name IN (...))
```

**Result: 0 foreign key constraints found** between any of the scoped tables.

The `owner_payout_accounts` table has no FK constraints in the current schema (before Phase A-F migrations). After Phase A-F migrations run, the dependency order will be:

```
properties (safelist — never deleted)
   └── owner_payout_accounts  (FK: property_id → properties.id, added by Phase A)
         ├── owner_balance_periods  (FK: owner_payout_account_id → opa.id)
         ├── owner_charges          (FK: owner_payout_account_id → opa.id)
         └── owner_statement_sends  (FK: owner_payout_account_id → opa.id,
                                          property_id → properties.id)
```

**Safe delete order** (for when the tables exist post-migration):
1. `owner_statement_sends` (child of `owner_payout_accounts`)
2. `owner_charges` (child of `owner_payout_accounts`)
3. `owner_balance_periods` (child of `owner_payout_accounts`)
4. `owner_payout_accounts` (parent — delete last)
5. `owner_magic_tokens` (independent, no FK to OPA)

---

## 4. Cleanup Script Summary

**File:** `backend/scripts/g1_cleanup_test_statement_data.sql`

The script is structured as follows:
- `BEGIN` + wrong-database abort guard
- Creates `_active_property_ids` temp table (14 rows) as a safelist
- **Step 0:** Pre-flight existence check for all 8 scoped tables
- **Step 1:** `owner_balance_periods` — skip (table missing)
- **Step 2:** `owner_charges` — skip (table missing)
- **Step 3:** `owner_payout_accounts` — detects 0 rows, no-op
- **Step 4:** `owner_magic_tokens` — counts 0 test rows, DELETE skipped
- **Steps 5-7:** `owner_statements`, `owner_statement_archive`, `payout_ledger` — count only, no deletes
- Final summary NOTICE block
- `ROLLBACK` (replace with `COMMIT` only after review)

Safety invariants encoded:
- Never deletes rows where `property_id` matches any of the 14 active properties
- Never deletes rows where `sl_owner_id` is non-null and non-empty (real Streamline IDs)
- Table existence checks before every step — safe to run before or after migrations
- Fully idempotent — running twice produces the same zero-delete result

---

## 5. Dry-Run Results

Executed with `ON_ERROR_STOP=0` and `ROLLBACK` at end.

### Step-by-step output

```
✓ Connected to fortress_guest
Active properties safelist: 14 rows

=== STEP 0: Table existence check ===
  ✗ MISSING  owner_balance_periods — Phase A-F migrations not yet applied
  ✗ MISSING  owner_charges — Phase A-F migrations not yet applied
  ✗ MISSING  owner_statement_sends — Phase A-F migrations not yet applied
  ✓ EXISTS   owner_payout_accounts
  ✓ EXISTS   owner_magic_tokens
  ✓ EXISTS   owner_statements
  ✓ EXISTS   owner_statement_archive
  ✓ EXISTS   payout_ledger

=== STEP 1: owner_balance_periods — TABLE DOES NOT EXIST, skipping ===
=== STEP 2: owner_charges — TABLE DOES NOT EXIST, skipping ===

=== STEP 3: owner_payout_accounts ===
  streamline_owner_id column present: f
  BEFORE: total rows = 0
  Table is empty — nothing to delete

=== STEP 4: owner_magic_tokens ===
  BEFORE: total rows = 7
  Test rows (email):                    0
  Test rows (expired+unused+no-sl-id):  0
  Total qualifying for deletion:        0
  NOTE: tokens for sl_owner_id=897648 (real owner) are PRESERVED
  ERROR: permission denied for table owner_magic_tokens
```

### The permission error on owner_magic_tokens

`fgp_app` does not have `DELETE` on `owner_magic_tokens`. The error is benign for this run — 0 rows qualified for deletion, so no DELETE would have executed anyway. This also means:

- If a future cleanup run ever does need to delete from `owner_magic_tokens`, it must be run as `fortress_admin` or with an explicit GRANT.
- The migration that creates/alters this table should ensure `fgp_app` has appropriate DML permissions.

**Transaction outcome:** The transaction aborted at Step 4 and automatically ROLLBACK'd. No data was modified. The final `ROLLBACK` statement was still executed and confirmed.

### Net rows deleted (dry-run)

| Table | Before | Would Delete | After |
|---|---|---|---|
| `owner_balance_periods` | N/A (missing) | 0 | N/A |
| `owner_charges` | N/A (missing) | 0 | N/A |
| `owner_payout_accounts` | 0 | 0 | 0 |
| `owner_magic_tokens` | 7 | 0 | 7 |
| `owner_statements` | 0 | 0 | 0 |
| `owner_statement_archive` | 9 | 0 | 9 |
| `payout_ledger` | 0 | 0 | 0 |

**Total rows that would be deleted: 0**

---

## 6. Uncertain Rows

### owner_magic_tokens — 3 expired unused tokens

Three tokens for `mkbuquoi0912@gmail.com` / `sl_owner_id=897648` expired without being used:

| id | created_at | expires_at | used_at |
|---|---|---|---|
| 6 | 2026-03-01 15:16:17 | 2026-03-02 15:16:17 | NULL |
| 3 | 2026-03-01 14:52:49 | 2026-03-02 14:52:49 | NULL |
| 1 | 2026-03-01 14:42:14 | 2026-03-02 14:42:14 | NULL |

**Classification:** Real owner data, not test data. A magic link flow that generates multiple tokens (e.g., user clicked "send again" multiple times) is normal behavior. These tokens are expired and harmless — they cannot be used again. The cleanup script correctly preserves them because `sl_owner_id` is non-null.

**Question for Gary:** Does this owner (`mkbuquoi0912@gmail.com`, `sl_owner_id=897648`) need to be re-onboarded before G.2 testing? They have no row in `owner_payout_accounts` — their portal invite was never completed.

### owner_statement_archive — sl_owner_id 897648 appears

The same sl_owner_id `897648` has 3 rows in `owner_statement_archive` (Jan, Dec, Nov statements). This confirms this is a real property owner whose Streamline statements were imported but who never completed the CROG portal invite.

---

## 7. Recommendation

**Do not run the COMMIT version of the cleanup script. It is unnecessary.**

The correct sequencing for G.2 to work is:

### Step G.1a — Apply Phase A-F Alembic migrations (prerequisite for G.2)
```bash
cd fortress-guest-platform
alembic -c backend/alembic.ini upgrade head
```

This will:
1. Run `c1a8f3b7e2d4` — adds `commission_rate` column to `owner_magic_tokens`
2. Run `d1e2f3a4b5c6` — creates `owner_balance_periods`, adds columns to `owner_payout_accounts`
3. Run `f8e1d2c3b4a5` — phase A5 offboard historical properties
4. Run `a3b5c7d9e1f2` — adds `is_owner_booking` to reservations
5. Run `c9e2f4a7b1d3` — creates `owner_charges`
6. Run `f1e2d3c4b5a6` — adds `voided_at`/`paid_by` to `owner_balance_periods`
7. Run `e5merge01` — merge point (no schema changes)
8. Run `b2c4d6e8f0a1` — adds acquisition documents table
9. Run `e7c3f9a1b5d2` — adds `commission_rate`/`streamline_owner_id` to `owner_payout_accounts`, creates `owner_statement_sends`

**NOTE:** Migration `e7c3f9a1b5d2` runs `DELETE FROM owner_payout_accounts` before adding the `NOT NULL` column. Since the table is already empty, this is a no-op.

### Step G.1b — Address the fgp_app permission gap
After migrations run, verify `fgp_app` has DML permissions on all new tables (`owner_balance_periods`, `owner_charges`, `owner_statement_sends`). The migration files include explicit `GRANT` statements for `fortress_api`; verify these cover `fgp_app` as well.

### Step G.1c — Onboard at least one real owner (required for G.2 UI to show data)
Without any rows in `owner_payout_accounts`, the statement list page will be empty on first load. The owner with `sl_owner_id=897648` (`mkbuquoi0912@gmail.com`) has archived Streamline statements but never completed their invite. Gary needs to decide:
- Re-send a magic link to that owner and have them complete onboarding, OR
- Use the admin onboarding flow to create an `owner_payout_accounts` row manually with the correct `commission_rate` and `streamline_owner_id`

### Step G.1d — Run the cleanup script post-migration as a sanity check
After migrations are applied, re-run the script in dry-run mode to confirm the counts are still clean. Then either COMMIT or determine it's still a no-op.

---

## 8. Confidence Rating

**Confidence: VERY HIGH that there is nothing to clean up.**

The DB has been examined at the query level. Every table in scope was inventoried. The test predicates were evaluated against real data. The result is consistent: the database is clean — not because cleanup was done, but because the statement workflow infrastructure (Phase A-F tables) simply hasn't been deployed to the database yet.

**Confidence: HIGH that running `alembic upgrade head` is safe.**

The migration `e7c3f9a1b5d2` documents it will `DELETE FROM owner_payout_accounts` — verified empty. The migration `d1e2f3a4b5c6` creates `owner_balance_periods` from scratch. None of the migrations touch `reservations`, `properties`, or any other live production table in a destructive way.

**One risk to flag:** The alembic migration chain has multiple branches converging at `e5merge01`. Before running `upgrade head`, run `alembic heads` to confirm there is exactly one unapplied head and no divergent branches. If there are multiple heads, resolve the merge before upgrading.

---

## Files Written This Phase

| File | Purpose |
|---|---|
| `backend/scripts/g1_cleanup_test_statement_data.sql` | Cleanup script (ROLLBACK mode — safe to re-run) |
| `backend/scripts/g1_cleanup_dryrun.log` | Full psql output from dry-run execution |
| `PHASE_G1_REPORT.md` | This report |

---

**STOPPED. Awaiting Gary's review before any further action.**  
**Do not proceed to G.2 until migrations are confirmed applied and at least one owner is enrolled.**
