-- =============================================================================
-- Phase G.1.5 — fortress_shadow owner-statement test data cleanup
-- =============================================================================
-- EXECUTE FORM: COMMIT at end. This permanently deletes data.
-- Dry-run validated in G.1.5. Backup taken before execution in G.1.6.
--
-- Pre-conditions (all verified 2026-04-15):
--   - DO NOT DELETE set: EMPTY. All 19,720 rows across 5 tables are test data.
--   - Gary reviewed g1_5_real_data_review.md and confirmed DELETE ALL.
--   - Backup has been taken via g1_5_backup_fortress_shadow.sh.
--
-- Delete order (respects FK RESTRICT constraints):
--   1. owner_statement_sends  (FK → owner_payout_accounts, FK → properties)
--   2. owner_charges           (FK → owner_payout_accounts)
--   3. owner_balance_periods   (FK → owner_payout_accounts)
--   4. owner_payout_accounts   (parent — no FK from other tables in scope)
--   5. owner_magic_tokens      (independent — no FK to any table in scope)
--
-- Safety invariants:
--   - Never deletes from properties, reservations, or any table outside the 5.
--   - Test predicates match ALL rows (verified pre-query confirms n = 0 real rows).
--   - Begin/rollback wrapping means any error leaves state unchanged.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ── Confirm we are on the correct database ────────────────────────────────────
DO $$
BEGIN
    IF current_database() != 'fortress_shadow' THEN
        RAISE EXCEPTION 'WRONG DATABASE: connected to %. Expected fortress_shadow. Aborting.',
            current_database();
    END IF;
    RAISE NOTICE 'Connected to fortress_shadow — OK';
END $$;

-- =============================================================================
-- STEP 0 — Pre-counts (must match numbers in g1_5_real_data_review.md)
-- =============================================================================

SELECT 'PRE owner_payout_accounts total'       AS label, COUNT(*) AS n FROM owner_payout_accounts;
SELECT 'PRE owner_payout_accounts test_rows'   AS label, COUNT(*) AS n FROM owner_payout_accounts
  WHERE owner_email ILIKE '%@test.com'
     OR owner_email ILIKE '%@example.com'
     OR owner_email IS NULL OR owner_email = '';
SELECT 'PRE owner_balance_periods total'       AS label, COUNT(*) AS n FROM owner_balance_periods;
SELECT 'PRE owner_charges total'               AS label, COUNT(*) AS n FROM owner_charges;
SELECT 'PRE owner_statement_sends total'       AS label, COUNT(*) AS n FROM owner_statement_sends;
SELECT 'PRE owner_magic_tokens total'          AS label, COUNT(*) AS n FROM owner_magic_tokens;

-- =============================================================================
-- STEP 1 — DELETE owner_statement_sends
-- =============================================================================
-- Reason: child of owner_payout_accounts (FK RESTRICT). Must be removed before
-- OPA rows can be deleted. All 55 rows link to test OPAs — confirmed by Task 3.

SELECT 'STEP1 would delete owner_statement_sends' AS label, COUNT(*) AS n
FROM owner_statement_sends
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

DELETE FROM owner_statement_sends
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

SELECT 'AFTER STEP1 owner_statement_sends remaining' AS label, COUNT(*) AS n
FROM owner_statement_sends;

-- =============================================================================
-- STEP 2 — DELETE owner_charges
-- =============================================================================
-- Reason: child of owner_payout_accounts (FK RESTRICT). All 311 rows link to
-- test OPAs — confirmed by Task 3 (oc_linked_to_real_opa = 0).

SELECT 'STEP2 would delete owner_charges' AS label, COUNT(*) AS n
FROM owner_charges
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

DELETE FROM owner_charges
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

SELECT 'AFTER STEP2 owner_charges remaining' AS label, COUNT(*) AS n
FROM owner_charges;

-- =============================================================================
-- STEP 3 — DELETE owner_balance_periods
-- =============================================================================
-- Reason: child of owner_payout_accounts (FK RESTRICT). All 17,692 rows link
-- to test OPAs (200 pre-2050 rows included — all test, obp_pre2050_linked_to_real = 0).

SELECT 'STEP3 would delete owner_balance_periods' AS label, COUNT(*) AS n
FROM owner_balance_periods
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

DELETE FROM owner_balance_periods
WHERE owner_payout_account_id IN (
    SELECT id FROM owner_payout_accounts
    WHERE owner_email ILIKE '%@test.com'
       OR owner_email ILIKE '%@example.com'
       OR owner_email IS NULL OR owner_email = ''
);

SELECT 'AFTER STEP3 owner_balance_periods remaining' AS label, COUNT(*) AS n
FROM owner_balance_periods;

-- =============================================================================
-- STEP 4 — DELETE owner_payout_accounts
-- =============================================================================
-- Reason: parent table. Children cleared in steps 1–3. All 1,261 rows are test
-- data — confirmed by Task 3 (opa_real_non_test = 0).

SELECT 'STEP4 would delete owner_payout_accounts' AS label, COUNT(*) AS n
FROM owner_payout_accounts
WHERE owner_email ILIKE '%@test.com'
   OR owner_email ILIKE '%@example.com'
   OR owner_email IS NULL OR owner_email = '';

DELETE FROM owner_payout_accounts
WHERE owner_email ILIKE '%@test.com'
   OR owner_email ILIKE '%@example.com'
   OR owner_email IS NULL OR owner_email = '';

SELECT 'AFTER STEP4 owner_payout_accounts remaining' AS label, COUNT(*) AS n
FROM owner_payout_accounts;

-- =============================================================================
-- STEP 5 — DELETE owner_magic_tokens
-- =============================================================================
-- Reason: independent table (no FK to owner_payout_accounts). All 401 rows
-- have @example.com emails and NULL/empty/TEST-prefix sl_owner_id — all synthetic.

SELECT 'STEP5 would delete owner_magic_tokens' AS label, COUNT(*) AS n
FROM owner_magic_tokens
WHERE owner_email ILIKE '%@test.com'
   OR owner_email ILIKE '%@example.com'
   OR owner_email IS NULL OR owner_email = ''
   OR sl_owner_id IS NULL OR sl_owner_id = ''
   OR sl_owner_id LIKE 'TEST%';

DELETE FROM owner_magic_tokens
WHERE owner_email ILIKE '%@test.com'
   OR owner_email ILIKE '%@example.com'
   OR owner_email IS NULL OR owner_email = ''
   OR sl_owner_id IS NULL OR sl_owner_id = ''
   OR sl_owner_id LIKE 'TEST%';

SELECT 'AFTER STEP5 owner_magic_tokens remaining' AS label, COUNT(*) AS n
FROM owner_magic_tokens;

-- =============================================================================
-- STEP 6 — Post-counts (all should be 0 if Gary confirmed DELETE ALL)
-- =============================================================================

SELECT 'POST owner_payout_accounts'   AS label, COUNT(*) AS n FROM owner_payout_accounts;
SELECT 'POST owner_balance_periods'   AS label, COUNT(*) AS n FROM owner_balance_periods;
SELECT 'POST owner_charges'           AS label, COUNT(*) AS n FROM owner_charges;
SELECT 'POST owner_statement_sends'   AS label, COUNT(*) AS n FROM owner_statement_sends;
SELECT 'POST owner_magic_tokens'      AS label, COUNT(*) AS n FROM owner_magic_tokens;

-- =============================================================================
-- G.1.6 EXECUTE: COMMIT — permanently deletes 19,720 test rows.
-- =============================================================================
COMMIT;

\echo 'EXECUTION COMPLETE — COMMIT executed. Data permanently modified.'
\echo 'Backup: backend/scripts/g1_5_backup_20260415_093236.sql (11 MB)'
\echo 'Restore: psql "$POSTGRES_ADMIN_URI" -f backend/scripts/g1_5_backup_20260415_093236.sql'
