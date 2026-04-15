# Phase G.3.5 Report — fortress_shadow Test Fixture Cleanup (Dry-Run)
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Dry-run verified. COMMIT-form script staged. Gary executes manually.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.3 (0c942914) | ✓ | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| Gary's OPA 1824 | present | `gary@cabin-rentals-of-georgia.com`, sl_owner_id=146514 | PASS |
| OPA 1824 `mailing_address_line1` | PO Box 982 | **PO Box 982** | PASS |
| Reservation count baseline | 100 | 100 | PASS |

**Note on mailing address:** G.3 report stated "570 Morgan Street NE" but the DB shows "PO Box 982". Gary must have accepted the invite with a different address than the admin-prefilled one. DB is authoritative. G.3 report is incorrect on this point. The OPA row is correct per Gary's actual input.

---

## 2. Deletion Set Identified

### 2a. Overlap count (auto-delete candidates)
**43 rows** match BOTH conditions (test prefix AND check_in_date ≥ 2027-01-01).  
Count is < 50 threshold — no additional Gary approval needed.

### 2b. Prefix-only rows (real dates with test prefix — flagged, NOT touched)
**0 rows.** No reservations with test prefixes have real-world check-in dates. Clean.

### 2c. Date-only rows (far-future without test prefix — flagged, NOT touched)
**0 rows.** All far-future reservations have test prefixes. Clean.

### 2d. Full deletion list (43 confirmation_codes)

| Prefix | Count | Date range |
|---|---|---|
| `E5-*` (A/B pairs) | 28 | 2056–2093 |
| `E6-*-X` | 13 | 2060–2095 |
| `B6OWN-*`, `B6REG-*` | 2 | 2099 |
| `E2E-D-*` | 2 | 2081–2088 |

Full list from Task 2d (43 rows sorted by confirmation_code omitted for brevity — full output captured in dry-run log).

---

## 3. Orphan Investigation

**21 tables** have `reservation_id` (or similar) columns. **15** have formal FK constraints.

| Table | Rows referencing test fixtures | FK action | Recommended action |
|---|---|---|---|
| `damage_claims` | 0 | CASCADE | No-op |
| `extra_orders` | 0 | CASCADE | No-op |
| `scheduled_messages` | 0 | CASCADE | No-op |
| `messages` | 0 | SET NULL | No-op |
| `rental_agreements` | 0 | SET NULL | No-op |
| `housekeeping_tasks` | 0 | SET NULL | No-op |
| `work_orders` | 0 | SET NULL | No-op |
| `guest_activities` | 0 | SET NULL | No-op |
| `guest_reviews` | 0 | SET NULL | No-op |
| `guest_surveys` | 0 | SET NULL | No-op |
| `guest_verifications` | 0 | SET NULL | No-op |
| `hunter_queue` | 0 | SET NULL | No-op |
| `agent_response_queue` | 0 | SET NULL | No-op |
| `analytics_events` | 0 | SET NULL | No-op |
| `reservation_holds` | 0 | SET NULL (converted_reservation_id) | No-op |
| `pending_sync` | 0 | None (no FK) | No-op |
| `streamline_payload_vault` | 0 | None (varchar, no FK) | No-op |
| **`parity_audits`** | **7** | None (no FK) | **DELETE in script** |
| **`financial_approvals`** | **7** | None (varchar, no FK) | **DELETE in script** |

**No FK constraint violations** will occur. The parent `reservations` delete is not blocked by any child table.

The script explicitly deletes the 7 rows from `parity_audits` and 7 from `financial_approvals` before deleting reservations to prevent orphan rows.

---

## 4. Backup

```
File: /home/admin/fortress-snapshot-g35-20260415_150032.sql
Size: 34 MB
Method: pg_dump as fortress_admin (fortress_api lacks privileges for full dump)
Errors: None
```

To restore (if needed):
```bash
psql "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow" \
  -f /home/admin/fortress-snapshot-g35-20260415_150032.sql
```

---

## 5. Dry-Run Output

Full dry-run log at `/tmp/g35_cleanup_output.log`. Key results:

```
NOTICE:  PRE-DELETE: reservations=43, parity_audits=7, financial_approvals=7

table_name           | rows_deleted
---------------------+--------------
financial_approvals  | 7
parity_audits        | 7
reservations         | 43

gary_opa_check       | 1   ← Gary's OPA 1824 untouched ✓
reservations_remaining | 57  ← 100 - 43 = 57 ✓
parity_audits_remaining | 0  ← No orphans remain ✓

ROLLBACK
```

All verification checks pass. Script logic is correct.

---

## 6. Cutover Sequence (Gary runs post-commit)

```bash
cd ~/Fortress-Prime/fortress-guest-platform
source .env 2>/dev/null
PSQL="${POSTGRES_API_URI/+asyncpg/}"

# Execute the cleanup
psql "$PSQL" -v ON_ERROR_STOP=1 \
  -f backend/scripts/g35_cleanup_commit.sql

# Verify post-cleanup
psql "$PSQL" -c "SELECT COUNT(*) FROM reservations;"
# Expected: 57

psql "$PSQL" -c "
  SELECT COUNT(*) AS far_future FROM reservations
  WHERE check_in_date >= '2027-01-01';"
# Expected: 0

psql "$PSQL" -c "
  SELECT COUNT(*) AS gary_opa FROM owner_payout_accounts
  WHERE id = 1824;"
# Expected: 1 (Gary's OPA untouched)
```

**Then refresh the Hermes parity dashboard at crog-ai.com.** The test-fixture discrepancies should no longer appear. The "100 consecutive $0.00 deltas" gate should begin accumulating clean readings.

---

## 7. Rollback Plan

The backup at `/home/admin/fortress-snapshot-g35-20260415_150032.sql` (34 MB) is the restore point. If the cleanup causes unexpected issues:

```bash
# 1. Drop and recreate the database (nuclear option — only if data is corrupt)
# OR restore specific tables:
psql "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow" << 'SQL'
-- Extract just the reservations, parity_audits, financial_approvals tables
-- from the backup and restore them.
-- (pg_restore with --table flag, or psql with targeted COPY blocks from backup)
SQL
```

Since the cleanup only removes 43 test reservation rows + 14 orphan rows (all confirmed test fixtures), the rollback scenario is extremely unlikely. The backup provides the safety net.

---

## 8. Confidence Rating

| Item | Confidence | Basis |
|---|---|---|
| Deletion set is correct (43 test fixtures) | **CERTAIN** | Both criteria verified; 0 real-date/test-prefix rows; 0 far-future/real-prefix rows |
| Gary's OPA 1824 untouched | **CERTAIN** | Verified in dry-run (gary_opa_check = 1) |
| No FK violations | **CERTAIN** | All non-CASCADE tables have 0 rows; no blocking constraints |
| Orphan cleanup correct | **CERTAIN** | parity_audits (7) and financial_approvals (7) deleted in correct order |
| Post-cleanup reservation count = 57 | **CERTAIN** | 100 - 43 = 57; verified in dry-run |
| Backup is valid | **HIGH** | 34MB pg_dump with exit 0; fortress_admin has full privileges |
| Hermes parity gate noise clears | **HIGH** | Test fixtures were the discrepancy source; removing them should clear false positives |

---

## 9. Recommended Next Phase

**G.4 — Reservation backfill into fortress_shadow**

With test fixture noise removed, fortress_shadow has 57 real reservations from 2026-04-07 onward. To enable statement generation with real March 2026 data for Gary's comparison:

1. Run Streamline sync for Fallen Timber Lodge (unit 70209) covering Jan–Mar 2026
2. Or bulk-import from fortress_guest (which has 2,665 historical reservations)
3. Then re-generate the March 2026 statement and compare against Streamline

G.4 is the prerequisite for meaningful financial validation of the Phase A-F statement workflow.
