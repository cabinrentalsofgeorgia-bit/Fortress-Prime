-- H.2 — Opening Balance Backfill — COMMIT
-- Run AFTER dry-run verifies correctly.
-- Date: 2026-04-16
--
-- Authoritative sources (Gary's March 2026 Streamline statements, NAS-archived):
--   Cherokee Sunrise  : opening = $64,822.71  | no March reservations → closing = $64,822.71
--   Serendipity       : opening = $306,170.38 | closing = $308,517.68 (Streamline confirmed)
--   Fallen Timber (25680): opening = $500,702.41 — UNTOUCHED

BEGIN;

-- ── Pre-update sentinel: Fallen Timber must be $500,702.41 / $504,738.26 ──────
DO $$
DECLARE
    v_opening numeric;
    v_closing numeric;
BEGIN
    SELECT opening_balance, closing_balance
    INTO v_opening, v_closing
    FROM owner_balance_periods WHERE id = 25680;
    IF v_opening != 500702.41 OR v_closing != 504738.26 THEN
        RAISE EXCEPTION 'PRE-FLIGHT FAILED: OBP 25680 (Fallen Timber) has unexpected values (opening=%, closing=%)', v_opening, v_closing;
    END IF;
    RAISE NOTICE 'PRE-FLIGHT: OBP 25680 opening=% closing=% — OK', v_opening, v_closing;
END;
$$;

-- ── Cherokee Sunrise: opening = closing = $64,822.71 ─────────────────────────
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

-- ── Serendipity: opening = $306,170.38 ───────────────────────────────────────
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

-- ── Post-update verification (all 3 Gary properties) ─────────────────────────
SELECT
    obp.id,
    p.name              AS property,
    obp.period_start,
    obp.period_end,
    obp.opening_balance,
    obp.closing_balance,
    obp.total_revenue,
    obp.total_commission,
    obp.status
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
JOIN properties p ON p.id::text = opa.property_id
WHERE obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31'
ORDER BY p.name;

-- ── Ledger equation checks ────────────────────────────────────────────────────
SELECT
    p.name                                                      AS property,
    obp.opening_balance,
    obp.closing_balance,
    (obp.opening_balance
     + obp.total_revenue
     - obp.total_commission
     - obp.total_charges
     - obp.total_payments
     + obp.total_owner_income)                                 AS expected_closing,
    abs(obp.closing_balance
        - (obp.opening_balance
           + obp.total_revenue
           - obp.total_commission
           - obp.total_charges
           - obp.total_payments
           + obp.total_owner_income)) <= 0.01                   AS within_one_cent
FROM owner_balance_periods obp
JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
JOIN properties p ON p.id::text = opa.property_id
WHERE obp.period_start = '2026-03-01'
  AND obp.period_end   = '2026-03-31'
ORDER BY p.name;
-- ALL rows must have within_one_cent = t before proceeding

-- ── Hard stop if any ledger check fails ──────────────────────────────────────
DO $$
DECLARE
    v_bad_count int;
BEGIN
    SELECT COUNT(*) INTO v_bad_count
    FROM owner_balance_periods obp
    JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
    WHERE opa.property_id IN (
        '50a9066d-fc2e-44c4-a716-25adb8fbad3e',
        '63bf8847-9990-4a36-9943-b6c160ce1ec4'
    )
      AND obp.period_start = '2026-03-01'
      AND abs(obp.closing_balance
              - (obp.opening_balance + obp.total_revenue - obp.total_commission
                 - obp.total_charges - obp.total_payments + obp.total_owner_income)
             ) > 0.01;

    IF v_bad_count > 0 THEN
        RAISE EXCEPTION 'LEDGER CHECK FAILED: % OBP(s) fail the closing_balance equation — ROLLBACK', v_bad_count;
    END IF;
    RAISE NOTICE 'LEDGER CHECK: all OBPs satisfy closing_balance equation — OK';
END;
$$;

-- ── Serendipity parity check against Streamline ($308,517.68) ────────────────
DO $$
DECLARE
    v_closing numeric;
    v_delta   numeric;
BEGIN
    SELECT obp.closing_balance INTO v_closing
    FROM owner_balance_periods obp
    JOIN owner_payout_accounts opa ON opa.id = obp.owner_payout_account_id
    WHERE opa.property_id = '63bf8847-9990-4a36-9943-b6c160ce1ec4'
      AND obp.period_start = '2026-03-01';

    v_delta := abs(v_closing - 308517.68);
    RAISE NOTICE 'SERENDIPITY PARITY: closing=% | target=308517.68 | delta=%', v_closing, v_delta;
    IF v_delta > 1.00 THEN
        RAISE WARNING 'SERENDIPITY closing % differs from Streamline $308,517.68 by $% (>$1). Investigate before approving.', v_closing, v_delta;
    END IF;
END;
$$;

COMMIT;
\echo '*** COMMIT COMPLETE — Opening balances applied for Cherokee and Serendipity ***'
