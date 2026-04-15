# Phase G.1.5 Report — fortress_shadow Cleanup (Dry-Run) & Test DB Isolation
**Date:** 2026-04-15  
**Status:** DRY-RUN ONLY. All changes staged, not committed. No data deleted. No production DB writes.  
**Commit:** Staged only — Gary must commit manually after reviewing `git diff --cached`.

---

## 1. Pre-Cleanup State (Task 1)

Live query against fortress_shadow (run 2026-04-15 as fortress_admin):

```sql
SELECT label, COUNT(*) AS n FROM (
  -- OPA breakdown
  SELECT 'opa_total' AS label FROM owner_payout_accounts
  UNION ALL SELECT 'opa_test_email_com' FROM ... -- etc.
) q GROUP BY label;
```

| Label | Count | Notes |
|---|---|---|
| `opa_total` | 1,261 | All rows |
| `opa_test_email_com` | 1,047 | ILIKE '%@test.com' |
| `opa_example_email_com` | 92 | ILIKE '%@example.com' |
| `opa_null_or_empty` | 122 | IS NULL OR = '' — names like "Period Test", "Charge Test Owner", "Unenrolled" |
| `opa_real_non_test` | **0** | Not matching any test pattern |
| `obp_total` | 17,692 | All rows |
| `obp_future_start_2050` | 17,492 | period_start ≥ 2050-01-01 |
| `obp_future_end_2050` | 17,492 | period_end ≥ 2050-01-01 |
| `obp_real_pre_2050` | 200 | period_start < 2050 |
| `obp_pre2050_linked_to_real_opa` | **0** | Pre-2050 rows linked to non-test OPA |
| `oc_total` | 311 | All charges |
| `oc_linked_to_test_opa` | 311 | All linked to test OPAs |
| `oc_linked_to_real_opa` | **0** | |
| `oss_total` | 55 | All statement sends |
| `oss_linked_to_test_opa` | 55 | All linked to test OPAs |
| `omt_total` | 401 | All magic tokens |
| `omt_test_email` | 401 | All match @example.com pattern |
| `omt_real_numeric_sl_id` | **0** | No real Streamline integer owner IDs |

### Drift from SYSTEM_ORIENTATION.md

| Claim in SYSTEM_ORIENTATION.md | Actual |
|---|---|
| "92 real (non-test email) OPA rows" | **0 real rows** — those 92 were @example.com test rows |
| "200 real balance periods" | **0 real rows** — all 200 pre-2050 OBPs link to test OPAs |
| "401 owner_magic_tokens (mix)" | All 401 are @example.com test tokens, zero real sl_owner_ids |

**Total confirmed test rows across all 5 tables: 19,720**  
**Confirmed real production rows across all 5 tables: 0**

---

## 2. FK Dependency Graph and Delete Order (Task 2)

Live query:
```sql
SELECT child_table, child_col, parent_table, parent_col, constraint_name, delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ...
JOIN information_schema.referential_constraints rc ...
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND (tc.table_name IN (...) OR ccu.table_name IN (...));
```

Result (4 FK constraints):

```
owner_payout_accounts  (parent — no inbound FKs from tables in scope)
  ← owner_balance_periods.owner_payout_account_id  (RESTRICT)
  ← owner_charges.owner_payout_account_id           (RESTRICT)
  ← owner_statement_sends.owner_payout_account_id   (RESTRICT)

properties (parent — inbound FK from owner_statement_sends only)
  ← owner_statement_sends.property_id               (RESTRICT)

owner_magic_tokens — NO FK relationship to any of the 5 tables (independent)
```

**No CASCADE rules.** All 4 constraints use `ON DELETE RESTRICT`. This means child rows must be deleted before parents.

**Correct delete order:**
1. `owner_statement_sends` (child of OPA and properties)
2. `owner_charges` (child of OPA)
3. `owner_balance_periods` (child of OPA)
4. `owner_payout_accounts` (parent — children cleared above)
5. `owner_magic_tokens` (independent — any order)

---

## 3. "DO NOT DELETE" Real-Data Set (Task 3)

**The set is empty.** All 19,720 rows across all 5 tables are test fixtures.

Reference: `backend/scripts/g1_5_real_data_review.md` — Gary must review and mark
any rows he wishes to preserve before G.1.6 executes the COMMIT form.

Evidence summary:
- `opa_real_non_test = 0` — zero OPA rows with non-test/non-example email
- All 200 pre-2050 OBP rows link to OPAs with `@test.com` or null/empty emails
- All 311 OC rows link to test OPAs (`oc_linked_to_real_opa = 0`)
- All 55 OSS rows link to test OPAs
- All 401 OMT rows have `@example.com` emails and no real numeric `sl_owner_id`

---

## 4. Backup Script (Task 4)

**File:** `backend/scripts/g1_5_backup_fortress_shadow.sh`  
**Status:** Created, `bash -n` passes, `chmod +x` applied. NOT executed in this phase.

**What it captures:** Full `--data-only --column-inserts` pg_dump of all 5 tables.  
Output format is plain INSERT statements — portable, human-readable, re-importable
into any Postgres instance without superuser.

**How to run before G.1.6:**
```bash
POSTGRES_ADMIN_URI="postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow" \
  bash backend/scripts/g1_5_backup_fortress_shadow.sh
# Writes: backend/scripts/g1_5_backup_YYYYMMDD_HHMMSS.sql
```

---

## 5. Cleanup Script (Task 5)

**File:** `backend/scripts/g1_5_cleanup_fortress_shadow.sql`  
**File:** `backend/scripts/g1_5_dryrun.log` — full psql output captured.

**Structure:** BEGIN → pre-counts → steps 1–5 (SELECT + DELETE per table) → post-counts → ROLLBACK.

### Dry-run output summary

Every step executed cleanly. Full output in `g1_5_dryrun.log`. Key rows:

```
NOTICE: Connected to fortress_shadow — OK

PRE owner_payout_accounts total   | 1261
PRE owner_payout_accounts test    | 1261
PRE owner_balance_periods total   | 17692
PRE owner_charges total           | 311
PRE owner_statement_sends total   | 55
PRE owner_magic_tokens total      | 401

STEP1 would delete owner_statement_sends | 55     → DELETE 55  → 0 remaining
STEP2 would delete owner_charges         | 311    → DELETE 311 → 0 remaining
STEP3 would delete owner_balance_periods | 17692  → DELETE 17692 → 0 remaining
STEP4 would delete owner_payout_accounts | 1261   → DELETE 1261 → 0 remaining
STEP5 would delete owner_magic_tokens    | 401    → DELETE 401  → 0 remaining

POST owner_payout_accounts   | 0
POST owner_balance_periods   | 0
POST owner_charges           | 0
POST owner_statement_sends   | 0
POST owner_magic_tokens      | 0

ROLLBACK
DRY RUN COMPLETE — ROLLBACK executed. No data was modified.
```

Exit code: 0. No errors or FK violations.

**Safety properties of the script:**
- Wrong-database guard at start (raises exception if not connected to `fortress_shadow`)
- All deletions inside `BEGIN/ROLLBACK` — zero state change in this phase
- SELECT counts before and after every DELETE
- Delete order matches FK dependency graph (children first)
- `\set ON_ERROR_STOP on` — any error aborts before ROLLBACK

**To execute for real (G.1.6):** Replace `ROLLBACK` with `COMMIT` at the bottom of the file.

---

## 6. Test DB Isolation — Files Created/Modified (Task 6)

### 6a. `backend/scripts/setup_test_db.sh` (new)

Creates `fortress_shadow_test` and brings it to alembic head. Idempotent.  
`bash -n` passes. `chmod +x` applied. NOT executed in this phase.

Steps:
1. `CREATE DATABASE fortress_shadow_test OWNER fortress_admin` (if not exists)
2. `GRANT CONNECT, USAGE, SELECT/INSERT/UPDATE/DELETE, SEQUENCE USAGE` to `fortress_api`
3. `POSTGRES_ADMIN_URI=...fortress_shadow_test alembic upgrade head`

### 6b. `backend/core/config.py` (modified)

**Change 1:** Added `import os` at top (needed for `os.getenv` in new property).

**Change 2:** Extended `ALLOWED_POSTGRES_DATABASES`:
```python
# Before:
ALLOWED_POSTGRES_DATABASES = frozenset({"fortress_prod", "fortress_shadow", "fortress_db"})

# After:
ALLOWED_POSTGRES_DATABASES = frozenset(
    {"fortress_prod", "fortress_shadow", "fortress_db", "fortress_shadow_test"}
)
```
This allows `TEST_DATABASE_URL` pointing at `fortress_shadow_test` to pass the settings validator.

**Change 3:** Added `test_database_url` property:
```python
@property
def test_database_url(self) -> str | None:
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        return None
    return self._rewrite_database_driver(raw, async_driver=True)
```

**Verified:** `python3 -c "from backend.core.config import settings; ..."` imports cleanly.
`settings.test_database_url` exists. `fortress_shadow_test` is in `ALLOWED_POSTGRES_DATABASES`.

### 6c. `backend/tests/conftest.py` (modified)

**Added:**
1. `import pytest` and `from backend.core.config import settings`
2. `pytest_configure` hook that prints a warning to stderr if `TEST_DATABASE_URL` is not set

**Not changed:** The existing `_dispose_shared_db_engine_after_test` fixture is untouched.

**Verified:** `pytest --collect-only backend/tests/` collects **796 tests** with no errors.

**What does NOT change yet:**
- The test suite still uses fortress_shadow by default (TEST_DATABASE_URL not required yet)
- The 23 test files that hardcode fortress_shadow DSNs still hardcode them (Task 6d)
- The warning is visible at test session start but does not fail tests

---

## 7. Phase A-F Test File DSN Follow-up List (Task 6d)

23 test files hardcode `DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"`.
These must be updated in a follow-up phase (G.1.7) to read from `TEST_DATABASE_URL` or
from `settings.test_database_url` instead.

**Do NOT edit these files in this phase.**

| File | Line | Hardcoded DSN |
|---|---|---|
| `test_channel_mappings.py` | 20 | `postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow` |
| `test_owner_statement_phase2.py` | 27 | same |
| `test_acquisition_area6.py` | 25 | same |
| `test_phase_d_statement_workflow.py` | 58 | same |
| `test_phase_e51_hygiene.py` | 130 | same |
| `test_phase_e6_visual_parity.py` | 27 | same |
| `test_owner_portal_area2.py` | 25 | same |
| `test_nas_storage.py` | 32 | same |
| `test_owner_statement_phase1.py` | 22 | same |
| `test_phase_e5_parity.py` | 52 | same |
| `test_phase_e_pdf.py` | 39 | same |
| `test_fee_integrity.py` | 15 | same (var name `SHADOW_DSN`) |
| `test_phase_b_revenue_fixes.py` | 19 | same |
| `test_housekeeping_area3.py` | 26 | same |
| `test_phase_c_owner_charges.py` | 71 | same |
| `test_owner_statement_phase3.py` | 38 | same |
| `test_phase_a_owner_ledger.py` | 28 | same |
| `test_stripe_connect_flow.py` | 32 | same |
| `test_owner_statement_phase1_5.py` | 32 | same |
| `test_phase_f_cron.py` | 58 | same |
| `test_seo_area4.py` | 25 | same |
| `test_workorders_area5.py` | 27 | same |
| `test_streamline_owner_balance_sync.py` | (grep) | same |

Total: 23 files. All must be updated to use:
```python
import os
DSN = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"
)
```

---

## 8. Known Issues, Uncertainties, "Needs Gary Decision"

1. **Gary must review `g1_5_real_data_review.md`** and mark the tables. If he leaves
   them blank (DELETE ALL), G.1.6 can proceed immediately. If he identifies any rows
   to preserve, the cleanup script WHERE clauses need updating with `id NOT IN (...)`.

2. **SYSTEM_ORIENTATION.md claimed "92 real" OPA rows.** This was incorrect. Those 92
   were @example.com test rows. SYSTEM_ORIENTATION.md should be updated to reflect
   that the DO NOT DELETE set is empty. Flagged as a follow-up doc update.

3. **`fortress_api` role may lack DELETE on `owner_magic_tokens`** (discovered in G.1 phase).
   The cleanup script runs as `fortress_admin` which has full privileges — this is correct.
   But `setup_test_db.sh` grants DELETE to `fortress_api` for the test DB. Verify
   `fortress_api` has DELETE on the 5 tables in fortress_shadow before trying to
   run the cleanup script as a non-admin user.

4. **`setup_test_db.sh` was NOT executed.** `fortress_shadow_test` does not exist yet.
   Running `setup_test_db.sh` will take alembic upgrade head against a fresh DB — this
   can take a few minutes and requires all migrations to succeed without errors.

5. **796 tests collected but none run.** The test suite against `fortress_shadow_test`
   hasn't been validated end-to-end. Some tests may fail on the empty test DB because
   they expect property or reservation rows from `fortress_shadow`'s production data.
   That gap is G.1.7 scope.

6. **Pyright false-positive warnings** in conftest.py:
   - `"_dispose_shared_db_engine_after_test" is not accessed` — expected for pytest
     fixtures; pytest injects them by name, not by direct call.
   - `"config" is not accessed` in `pytest_configure(config)` — the parameter is used
     for the type annotation only; this is standard pytest plugin pattern.
   Neither affects runtime behavior.

---

## 9. Confidence Rating

| Task | Confidence | Basis |
|---|---|---|
| Task 1: Pre-cleanup state | **CERTAIN** | Direct SQL queries; results verified |
| Task 2: FK dependency graph | **CERTAIN** | `information_schema` query; 4 constraints returned |
| Task 3: DO NOT DELETE set is empty | **VERY HIGH** | Three independent queries confirm 0 real rows |
| Task 4: Backup script | **HIGH** | `bash -n` passes; script logic is standard pg_dump pattern |
| Task 5: Cleanup script dry-run | **CERTAIN** | Ran against live fortress_shadow; all counts match; ROLLBACK confirmed |
| Task 6a: setup_test_db.sh | **HIGH** | `bash -n` passes; alembic part not exercised |
| Task 6b: config.py changes | **VERY HIGH** | Import test passes; property exists; allowed set verified |
| Task 6c: conftest.py changes | **VERY HIGH** | 796 tests collect without errors |
| Task 7: DSN follow-up list | **CERTAIN** | `grep -rn` output — 23 files, exact line numbers |

---

## 10. Recommended Next Steps

### G.1.6 — Execute the cleanup

1. Gary reviews `backend/scripts/g1_5_real_data_review.md` and confirms DELETE ALL
2. Run the backup: `bash backend/scripts/g1_5_backup_fortress_shadow.sh`
3. Edit `backend/scripts/g1_5_cleanup_fortress_shadow.sql`: replace `ROLLBACK` with `COMMIT`
4. Execute: `psql "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow" -f backend/scripts/g1_5_cleanup_fortress_shadow.sql`
5. Verify post-counts (all 5 tables = 0 rows)

### G.1.7 — Update test files and validate isolation

1. Execute `setup_test_db.sh` to create and migrate `fortress_shadow_test`
2. Update the 23 test files from §7 to read DSN from `TEST_DATABASE_URL` env var
3. Set `TEST_DATABASE_URL` in developer environment
4. Run `pytest backend/tests/` — confirm tests pass against the isolated test DB
5. Confirm fortress_shadow is no longer contaminated after a test run

---

## Files in this Staged Commit

| File | Change |
|---|---|
| `backend/scripts/g1_5_real_data_review.md` | New — Gary's review table |
| `backend/scripts/g1_5_backup_fortress_shadow.sh` | New — backup script |
| `backend/scripts/g1_5_cleanup_fortress_shadow.sql` | New — cleanup script (dry-run form) |
| `backend/scripts/g1_5_dryrun.log` | New — full dry-run output |
| `backend/scripts/setup_test_db.sh` | New — test DB setup script |
| `backend/core/config.py` | Modified — add `fortress_shadow_test` to allowed set, add `test_database_url` property |
| `backend/tests/conftest.py` | Modified — add `pytest_configure` warning |
| `PHASE_G15_REPORT.md` | New — this file |
