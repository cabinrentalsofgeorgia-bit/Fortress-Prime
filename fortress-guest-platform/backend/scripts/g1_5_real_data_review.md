# G.1.5 Real-Data Review
**Generated:** 2026-04-15  
**Purpose:** Gary reviews this file and marks any rows that should NOT be deleted.
**Verdict from analysis:** The "DO NOT DELETE" set is empty. All rows across all 5 tables are confirmed test fixtures.

---

## Determination Method

The SYSTEM_ORIENTATION.md (G.0.5) previously estimated 92 "real" OPA rows and 200 "real"
balance periods. On re-query in G.1.5, those estimates were incorrect:

| Claim | Was | Actual |
|---|---|---|
| OPA @example.com rows are "real" | 92 "real" | 92 @example.com **test** rows |
| Pre-2050 OBP rows linked to real OPA | "~200 real" | 0 — all 200 linked to test OPAs |
| Any OMT with real sl_owner_id | Uncertain | 0 — all 401 have NULL/empty/TEST-prefix sl_owner_id |

---

## owner_payout_accounts — 1,261 rows (ALL test)

```sql
-- Verified live 2026-04-15
SELECT
  COUNT(*) FILTER (WHERE owner_email ILIKE '%@test.com')            AS test_com,       -- 1047
  COUNT(*) FILTER (WHERE owner_email ILIKE '%@example.com')         AS example_com,    -- 92
  COUNT(*) FILTER (WHERE owner_email IS NULL OR owner_email = '')   AS null_or_empty,  -- 122
  COUNT(*) FILTER (
    WHERE owner_email NOT ILIKE '%@test.com'
      AND owner_email NOT ILIKE '%@example.com'
      AND owner_email IS NOT NULL AND owner_email != ''
  )                                                                  AS real_rows      -- 0
FROM owner_payout_accounts;
```

The 122 null/empty-email rows have owner_name values like "Period Test XXXXXXXX",
"Charge Test Owner XXXXXXXX", "Unenrolled XXXXXXXX", "Ledger Test XXXXXXXX" —
all clearly synthetic test fixture names from Phase A-F test suite.

**Gary: if there are any OPA rows you believe are real production data, list them here by id.**  
_(Leave blank to confirm full deletion is safe)_

| OPA id | Reason to preserve | Gary's decision |
|---|---|---|
| — | — | DELETE ALL |

---

## owner_balance_periods — 17,692 rows (ALL test)

```sql
-- Verified live 2026-04-15
SELECT
  COUNT(*) FILTER (WHERE period_start >= '2050-01-01')  AS future_dated,       -- 17492
  COUNT(*) FILTER (WHERE period_start < '2050-01-01'
    AND owner_payout_account_id IN (
      SELECT id FROM owner_payout_accounts
      WHERE owner_email ILIKE '%@test.com'
         OR owner_email ILIKE '%@example.com'
         OR owner_email IS NULL OR owner_email = ''
    ))                                                   AS pre2050_test_linked, -- 200
  COUNT(*) FILTER (WHERE period_start < '2050-01-01'
    AND owner_payout_account_id NOT IN (
      SELECT id FROM owner_payout_accounts
      WHERE owner_email ILIKE '%@test.com'
         OR owner_email ILIKE '%@example.com'
         OR owner_email IS NULL OR owner_email = ''
    ))                                                   AS pre2050_real_linked  -- 0
FROM owner_balance_periods;
```

The 200 pre-2050 rows are all linked to OPAs with owner_email like
`knight.mitchell.gary@test.com`, `dutil.david@test.com`, `ct-XXXXXXXX@test.com`, or
null/empty with "Period Test" names. All test data.

**Gary: if there are any OBP rows you believe are real production statements, list them here.**  
_(Leave blank to confirm full deletion is safe)_

| OBP id | period_start | period_end | owner_email | Reason to preserve | Gary's decision |
|---|---|---|---|---|---|
| — | — | — | — | — | DELETE ALL |

---

## owner_charges — 311 rows (ALL test)

```sql
-- Verified live 2026-04-15
SELECT
  COUNT(*) FILTER (WHERE opa.owner_email ILIKE '%@test.com'
                      OR opa.owner_email ILIKE '%@example.com'
                      OR opa.owner_email IS NULL OR opa.owner_email = '')  AS test_linked, -- 311
  COUNT(*) FILTER (WHERE opa.owner_email NOT ILIKE '%@test.com'
                     AND opa.owner_email NOT ILIKE '%@example.com'
                     AND opa.owner_email IS NOT NULL AND opa.owner_email != '') AS real_linked  -- 0
FROM owner_charges oc
JOIN owner_payout_accounts opa ON opa.id = oc.owner_payout_account_id;
```

**Gary: if there are any charge rows you believe are real production charges, list them here.**  
| Charge id | Reason to preserve | Gary's decision |
|---|---|---|
| — | — | DELETE ALL |

---

## owner_statement_sends — 55 rows (ALL test)

All 55 rows link to test OPAs.

**Gary:**  
| OSS id | Reason to preserve | Gary's decision |
|---|---|---|
| — | — | DELETE ALL |

---

## owner_magic_tokens — 401 rows (ALL test)

```sql
-- Verified live 2026-04-15
SELECT
  COUNT(*) FILTER (WHERE sl_owner_id IS NULL OR sl_owner_id = '' OR sl_owner_id LIKE 'TEST%') AS synthetic_sl_id, -- 401
  COUNT(*) FILTER (WHERE sl_owner_id ~ '^[0-9]+$')  AS real_numeric_sl_id  -- 0
FROM owner_magic_tokens;
```

All 401 tokens have @example.com emails (test-*, rate-test-*, roundtrip-*, e5-addr-rt-*,
legacy-*, etc.) and NULL/empty/TEST-prefixed sl_owner_id values. Zero real Streamline owner IDs.

**Gary:**  
| OMT id | Reason to preserve | Gary's decision |
|---|---|---|
| — | — | DELETE ALL |

---

## Summary Decision

If Gary leaves all tables blank (no exceptions), the cleanup script (G.1.6 commit) will:
- Delete all 55 owner_statement_sends
- Delete all 311 owner_charges  
- Delete all 17,692 owner_balance_periods
- Delete all 1,261 owner_payout_accounts
- Delete all 401 owner_magic_tokens

**Total rows to be deleted: 19,720**

Post-cleanup, all 5 tables will be empty and ready for real production owner onboarding.
