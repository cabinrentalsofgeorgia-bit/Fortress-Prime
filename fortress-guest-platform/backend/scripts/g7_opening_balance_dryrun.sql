-- =============================================================================
-- G.7 — Opening balance backfill for Gary Knight, Fallen Timber Lodge, March 2026
-- =============================================================================
-- DRY-RUN FORM: ROLLBACK at end. Gary changes to COMMIT manually.
--
-- Verified backfill value: $500,702.41
-- Verification: Streamline GetUnitOwnerBalance(unit_id=70209) returned
--   {"owner_balance": -504738.26} on 2026-04-15.
--   -504738.26 + 4035.85 (March owner net) = -500702.41 → absolute value =
--   $500,702.41, matching Gary's Streamline PDF for March 2026 exactly.
--
-- Data model: Model (ii) — direct UPDATE on owner_balance_periods.
--   opening_balance and closing_balance are columns on the OBP row.
--   The ledger CHECK constraint requires:
--     closing_balance = opening_balance + total_revenue - total_commission
--                       - total_charges - total_payments + total_owner_income
--   So both columns must be updated together.
--
-- OBP 25680 pre-update:
--   opening_balance = 0.00
--   total_revenue   = 6209.00
--   total_commission = 2173.15
--   total_owner_income = 0.00
--   closing_balance = 4035.85
--
-- OBP 25680 post-update (expected):
--   opening_balance = 500702.41
--   closing_balance = 504738.26 (= 500702.41 + 6209 - 2173.15)
-- =============================================================================

BEGIN;

-- === Pre-update state ===
SELECT 'PRE-UPDATE' AS label, id, opening_balance, closing_balance,
       total_revenue, total_commission, status
FROM owner_balance_periods WHERE id = 25680;

-- === Apply backfill ===
UPDATE owner_balance_periods
SET opening_balance = 500702.41,
    closing_balance = 500702.41 + total_revenue - total_commission
                      - total_charges - total_payments + total_owner_income,
    updated_at      = NOW()
WHERE id = 25680;

-- === Post-update verification ===
SELECT 'POST-UPDATE' AS label, id, opening_balance, closing_balance,
       total_revenue, total_commission, status
FROM owner_balance_periods WHERE id = 25680;

-- === Confirm the ledger equation holds ===
SELECT
  'ledger_check' AS label,
  id,
  opening_balance + total_revenue - total_commission
    - total_charges - total_payments + total_owner_income AS expected_closing,
  closing_balance AS actual_closing,
  ABS((opening_balance + total_revenue - total_commission
       - total_charges - total_payments + total_owner_income)
      - closing_balance) < 0.01 AS within_one_cent
FROM owner_balance_periods WHERE id = 25680;

-- === Gary's OPA untouched ===
SELECT COUNT(*) AS gary_opa_check FROM owner_payout_accounts WHERE id = 1824;

-- === DRY-RUN: ROLLBACK — Gary changes to COMMIT manually ===
ROLLBACK;
