-- =============================================================================
-- G.3.5 — fortress_shadow test fixture reservation cleanup
-- =============================================================================
-- DRY-RUN FORM: ROLLBACK at end. Gary changes to COMMIT manually.
--
-- Deletion criterion: BOTH conditions must be true:
--   1. confirmation_code matches a known test prefix (E5-, E6-, B6OWN-, B6REG-, E2E-)
--   2. check_in_date >= 2027-01-01 (far-future: 2056-2099)
--
-- Pre-backup: /home/admin/fortress-snapshot-g35-20260415_150032.sql (34 MB)
-- Orphan cleanup: parity_audits and financial_approvals also have 7 rows each
--   referencing test reservation IDs. Both tables have no FK constraint, so
--   deletion from reservations won't be blocked, but cleanup is included for
--   hygiene.
--
-- Run: psql "$PSQL" -f g35_cleanup_dryrun.sql
-- Commit form: g35_cleanup_commit.sql (ROLLBACK → COMMIT)
-- =============================================================================

BEGIN;

-- Audit table for this run
CREATE TEMP TABLE deletion_audit (table_name TEXT, rows_deleted INTEGER);

-- === Step 0: pre-counts ===
DO $$
DECLARE
  v_res  INTEGER;
  v_pa   INTEGER;
  v_fa   INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_res FROM reservations
    WHERE check_in_date >= '2027-01-01'
      AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
           OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
           OR confirmation_code LIKE 'E2E-%');
  SELECT COUNT(*) INTO v_pa FROM parity_audits
    WHERE reservation_id IN (
      SELECT id FROM reservations
      WHERE check_in_date >= '2027-01-01'
        AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
             OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
             OR confirmation_code LIKE 'E2E-%')
    );
  SELECT COUNT(*) INTO v_fa FROM financial_approvals
    WHERE reservation_id IN (
      SELECT id::text FROM reservations
      WHERE check_in_date >= '2027-01-01'
        AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
             OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
             OR confirmation_code LIKE 'E2E-%')
    );
  RAISE NOTICE 'PRE-DELETE: reservations=%, parity_audits=%, financial_approvals=%', v_res, v_pa, v_fa;
END $$;

-- === Step 1: parity_audits (no FK — delete before parent to avoid orphans) ===
WITH test_ids AS (
  SELECT id FROM reservations
  WHERE check_in_date >= '2027-01-01'
    AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
         OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
         OR confirmation_code LIKE 'E2E-%')
),
deleted AS (
  DELETE FROM parity_audits
  WHERE reservation_id IN (SELECT id FROM test_ids)
  RETURNING 1
)
INSERT INTO deletion_audit VALUES ('parity_audits', (SELECT COUNT(*) FROM deleted));

-- === Step 2: financial_approvals (varchar FK, no constraint — delete before parent) ===
WITH test_ids_text AS (
  SELECT id::text FROM reservations
  WHERE check_in_date >= '2027-01-01'
    AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
         OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
         OR confirmation_code LIKE 'E2E-%')
),
deleted AS (
  DELETE FROM financial_approvals
  WHERE reservation_id IN (SELECT id::text FROM test_ids_text)
  RETURNING 1
)
INSERT INTO deletion_audit VALUES ('financial_approvals', (SELECT COUNT(*) FROM deleted));

-- === Step 3: reservations (parent) ===
-- CASCADE tables (damage_claims, extra_orders, scheduled_messages) have 0 rows
-- and will fire CASCADE automatically (also no-op here).
-- SET NULL tables have 0 rows — no SET NULL operations will occur.
WITH deleted AS (
  DELETE FROM reservations
  WHERE check_in_date >= '2027-01-01'
    AND (confirmation_code LIKE 'E5-%' OR confirmation_code LIKE 'E6-%'
         OR confirmation_code LIKE 'B6OWN-%' OR confirmation_code LIKE 'B6REG-%'
         OR confirmation_code LIKE 'E2E-%')
  RETURNING 1
)
INSERT INTO deletion_audit VALUES ('reservations', (SELECT COUNT(*) FROM deleted));

-- === Audit output ===
SELECT * FROM deletion_audit ORDER BY table_name;

-- === Verification checks ===
SELECT COUNT(*) AS gary_opa_check FROM owner_payout_accounts WHERE id = 1824;
SELECT COUNT(*) AS reservations_remaining FROM reservations;
SELECT COUNT(*) AS parity_audits_remaining FROM parity_audits
  WHERE reservation_id IN (
    SELECT id FROM reservations
    WHERE check_in_date >= '2027-01-01'
  );

-- === BY DEFAULT, ROLLBACK. Gary changes to COMMIT manually. ===
ROLLBACK;
