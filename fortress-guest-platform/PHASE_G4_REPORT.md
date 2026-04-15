# Phase G.4 Report — Q1 2026 Reservation Backfill (Dry-Run)
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Dry-run verified. COMMIT-form script staged. Gary executes manually.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.3.5 (14fcdabf) | ✓ | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| fortress_shadow reservations | 57 | 57 | PASS |
| fortress_guest reachable as fortress_admin | yes | yes | PASS |
| Gary's OPA 1824 | present | `gary@cabin-rentals-of-georgia.com`, sl_owner_id=146514 | PASS |
| Gary's active properties | 3 active + 1 pre_launch | Fallen Timber (70209), Cherokee Sunrise (306758), Serendipity (70222) active; Restoration Luxury (1012373) pre_launch excluded | PASS |

---

## 2. Schema Comparison

### reservations table

| Category | Columns | Action |
|---|---|---|
| **IN SHADOW NOT IN GUEST** | `guest_email` (VARCHAR NOT NULL), `guest_name` (VARCHAR NOT NULL), `guest_phone` (VARCHAR NULL), `is_owner_booking` (BOOL NOT NULL DEFAULT false), `tax_breakdown` (JSONB NULL), `security_deposit_payment_method_id` (VARCHAR NULL) | `guest_email`/`guest_name` populated by JOIN against fortress_shadow.guests after guest insert; `is_owner_booking`=false; others NULL |
| **IN GUEST NOT IN SHADOW** | `tenant_id` (UUID NULL), `pricing_base_rate_snapshot` (NUMERIC), `pricing_adjustment_snapshot` (NUMERIC), `pricing_channel_id` (UUID), `pricing_rule_ref` (VARCHAR) | Ignored — no shadow equivalent |
| **TYPE DIFFERENCE** | `access_code_valid_from/until`, `created_at`, `updated_at`, `security_deposit_updated_at`: TIMESTAMP (guest) vs TIMESTAMPTZ (shadow) | CAST via `::timestamptz` |
| **COMPATIBLE** | All other 40+ columns | Direct copy |

**No TYPE INCOMPATIBLE columns. All NOT NULL shadow columns are satisfied.** Proceed confirmed.

**Critical finding: property UUIDs differ between databases.** A CASE expression maps guest property_ids to shadow property_ids at insert time.

### guests table

| Category | Columns | Action |
|---|---|---|
| **Column rename** | `phone_number` (guest) → `phone` (shadow) | Column alias in SELECT |
| **IN SHADOW NOT IN GUEST** | Many enrichment columns (vehicle info, emergency contact, address fields) | NULL on insert |
| **IN GUEST NOT IN SHADOW** | `streamline_guest_id`, `notes`, `tags` | Ignored |
| **TYPE DIFFERENCE** | `created_at`, `updated_at`: TIMESTAMP → TIMESTAMPTZ | CAST |

**No blockers. ON CONFLICT (id) DO NOTHING handles existing guests.**

---

## 3. Source Data Identified

### Property UUID mapping (critical — UUIDs differ between databases)

| Property | fortress_guest UUID | fortress_shadow UUID |
|---|---|---|
| Fallen Timber Lodge | `1781fd69-a7e3-4df6-9216-c6152c9c19b6` | `93b2253d-7ae4-4d6f-8be2-125d33799c88` |
| Cherokee Sunrise on Noontootla Creek | `099f273a-6d2b-4eeb-9474-80fd89c18071` | `50a9066d-fc2e-44c4-a716-25adb8fbad3e` |
| Serendipity on Noontootla Creek | `bdef1b0d-8c7c-4126-a9d9-249b3d6b2621` | `63bf8847-9990-4a36-9943-b6c160ce1ec4` |

### Reservation counts in fortress_guest (Q1 2026, Gary's 3 properties)

| Period | Count |
|---|---|
| January 2026 | 4 |
| February 2026 | 6 |
| March 2026 | 6 |
| **Total** | **16** |

### Sample reservations (top 5 most recent)

| Code | Check-in | Check-out | Amount | Status | Property |
|---|---|---|---|---|---|
| 53765 | 2026-03-27 | 2026-03-29 | $2,471.66 | confirmed | Fallen Timber Lodge |
| 54020 | 2026-03-20 | 2026-03-22 | $2,033.24 | confirmed | Serendipity |
| 53952 | 2026-03-16 | 2026-03-21 | $4,967.81 | checked_in | Fallen Timber Lodge |
| 54012 | 2026-03-13 | 2026-03-15 | $2,110.13 | checked_out | Serendipity |
| 53870 | 2026-03-06 | 2026-03-08 | $1,954.14 | checked_out | Serendipity |

### Unique guests: 16

---

## 4. Conflict Check

Source codes: `53409, 53545, 53569, 53580, 53700, 53711, 53765, 53790, 53836, 53844, 53869, 53870, 53880, 53952, 54012, 54020`

**Already in fortress_shadow: 0**  
**New rows to insert: 16 reservations + 16 guests**

---

## 5. Backup

```
File: /home/admin/fortress-snapshot-g4-20260415_151658.sql
Size: 34 MB
Exit: 0
Method: pg_dump as fortress_admin
```

---

## 6. Dry-Run Results

Full log at `/tmp/g4_dryrun_output.log`. Key output:

```
dblink_connect: OK

step | table_name   | inserted | skipped
-----|--------------|----------|---------
  1  | guests       |    16    |    0
  2  | reservations |    16    |    0

total_reservations_post | 73   ← 57 + 16 = 73 ✓
gary_q1_reservations    | 16   ✓
gary_march_reservations |  6   ✓ (6 March reservations for statement)
gary_opa                |  1   ✓ (OPA 1824 untouched)

ROLLBACK
```

**All verification checks pass.** Script logic is correct.

### Extension used: dblink

dblink is installed in fortress_shadow (`SELECT extname FROM pg_extension WHERE extname='dblink'` → `dblink`). The script connects to fortress_guest as fortress_admin via dblink, queries source data, and inserts into fortress_shadow in a single transaction. No CSV intermediate files needed.

---

## 7. Cutover Sequence (Gary runs post-commit)

```bash
cd ~/Fortress-Prime/fortress-guest-platform
source .env 2>/dev/null
PSQL="${POSTGRES_API_URI/+asyncpg/}"

# Execute the backfill
psql "$PSQL" -v ON_ERROR_STOP=1 \
  -f backend/scripts/g4_backfill_commit.sql

# Verify post-backfill
psql "$PSQL" -c "SELECT COUNT(*) FROM reservations;"
# Expected: 73

psql "$PSQL" -c "
SELECT
  COUNT(*) AS gary_q1_total,
  COUNT(*) FILTER (WHERE check_in_date >= '2026-03-01' AND check_in_date < '2026-04-01') AS march
FROM reservations
WHERE property_id IN (
  '93b2253d-7ae4-4d6f-8be2-125d33799c88',
  '50a9066d-fc2e-44c4-a716-25adb8fbad3e',
  '63bf8847-9990-4a36-9943-b6c160ce1ec4'
)
AND check_in_date >= '2026-01-01'
AND check_in_date < '2026-04-01';"
# Expected: gary_q1_total=16, march=6

# Then re-generate March 2026 statement:
# 1. Navigate to https://crog-ai.com/admin/statements
# 2. Click "Generate Statements"
# 3. Set period: 2026-03-01 to 2026-03-31
# 4. Preview → Confirm & Generate
# The draft should now show non-zero totals for Fallen Timber Lodge,
# Cherokee Sunrise, and Serendipity.
# 5. Download the PDF and compare against Streamline March 2026 statement.
```

---

## 8. Rollback Plan

The backup at `/home/admin/fortress-snapshot-g4-20260415_151658.sql` (34MB) is the restore point.

Since the backfill only adds 16 new reservations and 16 new guests (ON CONFLICT DO NOTHING), rollback is simple:

```bash
# Delete the backfilled reservations
psql "$PSQL" -c "
DELETE FROM reservations
WHERE confirmation_code IN (
  '53409','53545','53569','53580','53700','53711','53765','53790',
  '53836','53844','53869','53870','53880','53952','54012','54020'
);"

# Delete the backfilled guests (only if not referenced elsewhere)
# WARNING: verify no other reservations reference these guest IDs first
```

---

## 9. Confidence Rating

| Item | Confidence | Basis |
|---|---|---|
| Source data correct (16 reservations, Gary's properties) | **VERY HIGH** | Verified by sampling; confirmation codes match expected Streamline numbering |
| Property UUID mapping correct | **CERTAIN** | Verified name-to-UUID in both DBs explicitly |
| Schema compatibility | **CERTAIN** | All NOT NULL columns satisfied; CAST types verified |
| 0 conflicts | **CERTAIN** | All 16 confirmation codes absent from fortress_shadow |
| Dry-run clean | **CERTAIN** | Exit 0, 16+16 inserted, correct post-counts |
| Gary's OPA 1824 untouched | **CERTAIN** | Verified in dry-run (gary_opa=1) |
| March 2026 statement will have non-zero totals | **HIGH** | 6 March reservations now available; statement computation should find them |

---

## 10. Recommended Next Steps

### After Gary executes commit + re-runs March 2026 statement generation:

1. **Download the CROG PDF** (via `/admin/statements/{id}/pdf`)
2. **Open Streamline March 2026 statement** for Gary's 3 properties
3. **Compare against G.3 checklist** (`backend/scripts/g3_comparison_checklist.md`):
   - Reservation count: expect 6 March check-ins
   - Revenue totals per property
   - Commission amounts (35% of gross)
   - Closing balance

### If parity validates:
**G.5** — Broader backfill across all 14 active owners and longer history (Jan 2025 – Mar 2026). The G.4 script pattern (dblink + property UUID mapping + CASE expression) scales directly.

### If parity fails:
Investigate `compute_owner_statement` math against the backfilled data. Possible issues:
- Reservation `status` field values may differ from what the computation expects
- `total_amount` vs line-item breakdown (cleaning_fee, service_fee, etc.) — statement computation may use different fields
- Owner booking flag (`is_owner_booking=false` correct for all 16 rows)
