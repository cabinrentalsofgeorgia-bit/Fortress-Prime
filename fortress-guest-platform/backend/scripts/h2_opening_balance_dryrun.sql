-- H.2 — Opening Balance Backfill — DRY RUN (ROLLBACK)
-- Run AFTER h2_opa_insert.sql (COMMIT) AND h2_generate_obps.py
-- Date: 2026-04-16
--
-- Authoritative sources (Gary's March 2026 Streamline statements, NAS-archived):
--   Cherokee Sunrise   : March 1 opening = $64,822.71  | no March reservations
--   Serendipity        : March 1 opening = $306,170.38 | closing = $308,517.68
--   Fallen Timber Lodge: OBP 25680, opening = $500,702.41 — UNTOUCHED

BEGIN;

-- ── Pre-update state ──────────────────────────────────────────────────────────
\echo '=== PRE-UPDATE STATE ==='
SELECT
    obp.id,
    p.name            AS property,
    obp.period_start,
    obp.period_end,
    obp.opening_balance,
    obp.closing_balance,
    obp.total_revenue,
    obp.total_commission,
    obp.total_charges,
    obp.total_payments,
    obp.total_owner_income,
    obp.status
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
JOIN properties p ON p.id::text = opa.property_id
WHERE obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31'
ORDER BY p.name;

-- ── Cherokee Sunrise: opening = closing = $64,822.71 (no March reservations) ─
UPDATE owner_balance_periods obp
SET
    opening_balance = 64822.71,
    closing_balance = 64822.71
        + obp.total_revenue
        - obp.total_commission
        - obp.total_charges
        - obp.total_payments
        + obp.total_owner_income
FROM owner_payout_accounts opa
WHERE obp.owner_payout_account_id = opa.id
  AND opa.property_id = '50a9066d-fc2e-44c4-a716-25adb8fbad3e'
  AND obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31';

-- ── Serendipity: opening = $306,170.38, closing = opening + March net ─────────
UPDATE owner_balance_periods obp
SET
    opening_balance = 306170.38,
    closing_balance = 306170.38
        + obp.total_revenue
        - obp.total_commission
        - obp.total_charges
        - obp.total_payments
        + obp.total_owner_income
FROM owner_payout_accounts opa
WHERE obp.owner_payout_account_id = opa.id
  AND opa.property_id = '63bf8847-9990-4a36-9943-b6c160ce1ec4'
  AND obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31';

-- ── Post-update verification ──────────────────────────────────────────────────
\echo ''
\echo '=== POST-UPDATE STATE ==='
SELECT
    obp.id,
    p.name            AS property,
    obp.opening_balance,
    obp.closing_balance,
    obp.total_revenue,
    obp.total_commission,
    obp.total_charges,
    obp.status
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
JOIN properties p ON p.id::text = opa.property_id
WHERE obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31'
ORDER BY p.name;

-- ── Ledger equation checks ────────────────────────────────────────────────────
\echo ''
\echo '=== LEDGER EQUATION CHECKS ==='
SELECT
    p.name                                          AS property,
    obp.opening_balance,
    obp.closing_balance,
    -- Formula: closing = opening + revenue - commission - charges - payments + income
    (obp.opening_balance
     + obp.total_revenue
     - obp.total_commission
     - obp.total_charges
     - obp.total_payments
     + obp.total_owner_income)                     AS expected_closing,
    abs(obp.closing_balance
        - (obp.opening_balance
           + obp.total_revenue
           - obp.total_commission
           - obp.total_charges
           - obp.total_payments
           + obp.total_owner_income)) <= 0.01       AS within_one_cent
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
JOIN properties p ON p.id::text = opa.property_id
WHERE obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31'
ORDER BY p.name;
-- Expected: all within_one_cent = t

-- ── Serendipity closing parity check against Streamline ($308,517.68) ─────────
\echo ''
\echo '=== SERENDIPITY PARITY CHECK (target closing: $308,517.68) ==='
SELECT
    obp.opening_balance,
    obp.closing_balance,
    abs(obp.closing_balance - 308517.68)            AS delta_vs_streamline,
    abs(obp.closing_balance - 308517.68) <= 1.00    AS within_one_dollar
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
WHERE opa.property_id = '63bf8847-9990-4a36-9943-b6c160ce1ec4'
  AND obp.period_start = '2026-03-01';
-- Expected: within_one_dollar = t

-- ── Fallen Timber untouched check ────────────────────────────────────────────
\echo ''
\echo '=== FALLEN TIMBER LODGE SENTINEL (must be $500,702.41 / $504,738.26) ==='
SELECT
    obp.id,
    obp.opening_balance,
    obp.closing_balance,
    obp.opening_balance = 500702.41 AS opening_correct,
    obp.closing_balance = 504738.26 AS closing_correct
FROM owner_balance_periods obp
WHERE obp.id = 25680;
-- Expected: both = t

ROLLBACK;
\echo ''
\echo '*** DRY RUN COMPLETE — ROLLED BACK. Review output, then run commit script. ***'
