# Phase G.1.6 Report — fortress_shadow Test Data Cleanup Execution
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Type:** Irreversible — 19,720 rows permanently deleted from fortress_shadow.  
**Status:** COMPLETE. All 5 target tables now contain 0 rows.

---

## 1. Pre-Execution State

### Pre-flight verification results

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | `feature/owner-statements-and-stabilization` | ✓ PASS |
| `g1_5_cleanup_fortress_shadow.sql` exists | yes | yes (8,770 bytes) | ✓ PASS |
| `g1_5_backup_fortress_shadow.sh` exists | yes | yes (2,737 bytes, executable) | ✓ PASS |
| `g1_5_real_data_review.md` exists | yes | yes (5,442 bytes) | ✓ PASS |
| DO NOT DELETE set empty | all tables "DELETE ALL" | confirmed — zero rows preserved | ✓ PASS |
| DB connection | `fortress_shadow \| fortress_admin` | `fortress_shadow \| fortress_admin` | ✓ PASS |

### Pre-execution row counts (verified live, matched G.1.5 within 0% drift)

| Table | G.1.5 count | G.1.6 pre-count | Drift |
|---|---|---|---|
| `owner_payout_accounts` | 1,261 | **1,261** | 0 |
| `owner_balance_periods` | 17,692 | **17,692** | 0 |
| `owner_charges` | 311 | **311** | 0 |
| `owner_statement_sends` | 55 | **55** | 0 |
| `owner_magic_tokens` | 401 | **401** | 0 |
| **Total** | **19,720** | **19,720** | **0** |

No new test rows accumulated between G.1.5 and G.1.6. Counts match exactly.

---

## 2. Backup Details

| Property | Value |
|---|---|
| Script | `backend/scripts/g1_5_backup_fortress_shadow.sh` |
| Output file | `backend/scripts/g1_5_backup_20260415_093236.sql` |
| File size | **11 MB** |
| Format | `--data-only --column-inserts` (plain INSERT statements, portable) |
| Tables covered | `owner_payout_accounts`, `owner_balance_periods`, `owner_charges`, `owner_statement_sends`, `owner_magic_tokens` |
| Row count covered | 19,720 (all rows present at backup time) |
| Timestamp | 2026-04-15 09:32:36 |

The backup file is committed to git as part of this phase (via staging). It can also be kept locally as a standalone restore artifact.

**To restore from backup:**
```bash
POSTGRES_ADMIN_URI=$(grep '^POSTGRES_ADMIN_URI' .env | head -1 | cut -d= -f2- | tr -d '"' | sed 's|postgresql+asyncpg://|postgresql://|')
psql "$POSTGRES_ADMIN_URI" -f backend/scripts/g1_5_backup_20260415_093236.sql
```

---

## 3. SQL File Diff Verification

Diff between `g1_5_cleanup_fortress_shadow.sql` (dry-run) and `g1_6_cleanup_fortress_shadow_committed.sql` (execute):

```diff
4,5c4,5
< -- DRY-RUN FORM: ROLLBACK at the end. No data is permanently modified.
< -- To execute for real: swap ROLLBACK for COMMIT (Phase G.1.6).
---
> -- EXECUTE FORM: COMMIT at end. This permanently deletes data.
> -- Dry-run validated in G.1.5. Backup taken before execution in G.1.6.
186c186
< -- DRY-RUN: ROLLBACK — swap for COMMIT in G.1.6 after Gary's review.
---
> -- G.1.6 EXECUTE: COMMIT — permanently deletes 19,720 test rows.
188c188
< ROLLBACK;
---
> COMMIT;
190,191c190,192
< \echo 'DRY RUN COMPLETE — ROLLBACK executed. No data was modified.'
< \echo 'To commit: edit this file, replace ROLLBACK with COMMIT, re-run as fortress_admin.'
---
> \echo 'EXECUTION COMPLETE — COMMIT executed. Data permanently modified.'
> \echo 'Backup: backend/scripts/g1_5_backup_20260415_093236.sql (11 MB)'
> \echo 'Restore: psql "$POSTGRES_ADMIN_URI" -f ...'
```

**Exactly 4 sections changed** — header comment, section comment, ROLLBACK→COMMIT, \echo messages. All DELETE logic, WHERE clauses, pre/post counts, and safety guards are byte-identical to the validated dry-run.

---

## 4. Execution Log Summary

Full log: `backend/scripts/g1_6_execution.log`

| Step | Table | Rows deleted | Post-step count |
|---|---|---|---|
| 0 | Pre-counts (all tables) | — | PRE: 1261 / 17692 / 311 / 55 / 401 |
| 1 | `owner_statement_sends` | **55** | 0 |
| 2 | `owner_charges` | **311** | 0 |
| 3 | `owner_balance_periods` | **17,692** | 0 |
| 4 | `owner_payout_accounts` | **1,261** | 0 |
| 5 | `owner_magic_tokens` | **401** | 0 |
| — | **Total deleted** | **19,720** | — |
| — | COMMIT | — | `COMMIT` |

**psql exit code: 0**  
**Final message:** `EXECUTION COMPLETE — COMMIT executed. Data permanently modified.`

---

## 5. Post-Execution Verification

### Target tables (independent re-query)

```sql
SELECT 'owner_payout_accounts', COUNT(*) FROM owner_payout_accounts
UNION ALL SELECT 'owner_balance_periods', COUNT(*) FROM owner_balance_periods
UNION ALL SELECT 'owner_charges', COUNT(*) FROM owner_charges
UNION ALL SELECT 'owner_statement_sends', COUNT(*) FROM owner_statement_sends
UNION ALL SELECT 'owner_magic_tokens', COUNT(*) FROM owner_magic_tokens;
```

| Table | Count |
|---|---|
| `owner_payout_accounts` | **0** ✓ |
| `owner_balance_periods` | **0** ✓ |
| `owner_charges` | **0** ✓ |
| `owner_statement_sends` | **0** ✓ |
| `owner_magic_tokens` | **0** ✓ |

### Collateral tables (must be unchanged)

```sql
SELECT 'properties', COUNT(*) FROM properties
UNION ALL SELECT 'reservations', COUNT(*) FROM reservations
UNION ALL SELECT 'guests', COUNT(*) FROM guests
UNION ALL SELECT 'staff_users', COUNT(*) FROM staff_users;
```

| Table | Expected (SYSTEM_ORIENTATION.md) | Actual | Result |
|---|---|---|---|
| `properties` | 98 | **98** | ✓ PASS |
| `reservations` | 100 | **100** | ✓ PASS |
| `guests` | 125 | **125** | ✓ PASS |
| `staff_users` | 5 | **5** | ✓ PASS |

**No collateral damage.** The DELETE operations respected all FK constraints and only touched the 5 specified tables.

---

## 6. Alembic Head Unchanged

```sql
SELECT version_num FROM alembic_version;
-- Result: e6a1b2c3d4f5
```

✓ Alembic head is still `e6a1b2c3d4f5` — the data-only cleanup left the schema untouched.

---

## 7. Recovery Instructions

If the deleted data needs to be restored for any reason:

```bash
# 1. Ensure you are connected to fortress_shadow as fortress_admin
POSTGRES_ADMIN_URI=$(grep '^POSTGRES_ADMIN_URI' .env | head -1 | cut -d= -f2- | tr -d '"' | sed 's|postgresql+asyncpg://|postgresql://|')

# 2. Restore from backup (idempotent — INSERT statements, will fail on duplicate if rows exist)
psql "$POSTGRES_ADMIN_URI" \
  -f backend/scripts/g1_5_backup_20260415_093236.sql

# The backup uses --column-inserts format, so each row is a named INSERT statement.
# If restoration fails due to FK constraint order, restore in this order:
#   1. owner_payout_accounts (parent)
#   2. owner_balance_periods, owner_charges (children of OPA)
#   3. owner_statement_sends (grandchild of OPA)
#   4. owner_magic_tokens (independent)
```

The backup file is 11 MB and contains all 19,720 rows as plain INSERT statements. It can be imported into any PostgreSQL instance with the same schema.

**Note:** The deleted rows were 100% confirmed test data (zero real production rows). Restoration is an option but there is no business reason to restore them.

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| 19,720 test rows deleted | **CERTAIN** — psql exit 0, COMMIT confirmed, independent re-query = 0 |
| Zero real rows deleted | **CERTAIN** — G.1.5 verified opa_real_non_test=0, obp_pre2050_linked_to_real=0 |
| No collateral damage | **CERTAIN** — properties(98), reservations(100), guests(125), staff_users(5) all unchanged |
| Backup sufficient for recovery | **HIGH** — 11MB file with column-inserts format; tables were empty at start |
| Alembic schema unchanged | **CERTAIN** — version_num still e6a1b2c3d4f5 |

---

## 9. Recommended Next Phases (Gary's choice)

### Option A: G.1.7 — Test isolation execution

Run `backend/scripts/setup_test_db.sh` to create `fortress_shadow_test` and bring it to alembic head. Then update the 23 test files with hardcoded fortress_shadow DSNs to use `TEST_DATABASE_URL`. This isolates future test runs from production data.

### Option B: G.0.6 docs follow-up — Mark auth gap as resolved

The G.0.6 docs (`permission-matrix.md`, `api-surface-auth-classification.md`, `privileged-surface-checklist.md`) still have the G.0.7 auth gap marked as open. A small docs-only commit to mark it resolved.

### Option C: G.2 — Admin Statement Workflow UI

With fortress_shadow now clean and the Phase A-F backend fully committed, the frontend build can begin:
- Types + hooks for `OwnerBalancePeriod` in `hooks.ts`
- Page at `apps/command-center/src/app/(dashboard)/admin/statements/page.tsx`
- Navigation update in `navigation.ts`

Note: G.2 requires at least one real owner to be enrolled in `owner_payout_accounts` for the UI to display data. That enrollment step (onboarding a real owner) should happen before or alongside G.2.
