-- H.2 — Create OPAs for Cherokee Sunrise and Serendipity on Noontootla Creek
-- Gary Knight (sl_owner 146514) — same terms as Fallen Timber Lodge (OPA 1824)
-- stripe_account_id = NULL: Gary has one Stripe account (uq constraint on that col).
--   OBP generation for these OPAs uses h2_generate_obps.py which queries by
--   streamline_owner_id, bypassing the stripe_account_id IS NOT NULL filter in
--   generate_monthly_statements. Stripe payouts for these properties share OPA 1824's
--   account — a future migration can consolidate when needed.
-- Run ONCE. ON CONFLICT (property_id) is idempotent.
-- Date: 2026-04-16

BEGIN;

-- Pre-flight: confirm OPA 1824 (Fallen Timber) intact
DO $$
DECLARE
    v_count int;
BEGIN
    SELECT COUNT(*) INTO v_count FROM owner_payout_accounts WHERE id = 1824;
    IF v_count != 1 THEN
        RAISE EXCEPTION 'PRE-FLIGHT FAILED: OPA 1824 not found';
    END IF;
    RAISE NOTICE 'PRE-FLIGHT: OPA 1824 present — OK';
END;
$$;

-- Pre-flight: confirm both properties exist in fortress_shadow
DO $$
DECLARE
    v_cherokee_id uuid;
    v_serendipity_id uuid;
BEGIN
    SELECT id INTO v_cherokee_id
    FROM properties WHERE id = '50a9066d-fc2e-44c4-a716-25adb8fbad3e';
    IF v_cherokee_id IS NULL THEN
        RAISE EXCEPTION 'PRE-FLIGHT FAILED: Cherokee Sunrise not found in properties';
    END IF;
    RAISE NOTICE 'PRE-FLIGHT: Cherokee Sunrise UUID % present — OK', v_cherokee_id;

    SELECT id INTO v_serendipity_id
    FROM properties WHERE id = '63bf8847-9990-4a36-9943-b6c160ce1ec4';
    IF v_serendipity_id IS NULL THEN
        RAISE EXCEPTION 'PRE-FLIGHT FAILED: Serendipity not found in properties';
    END IF;
    RAISE NOTICE 'PRE-FLIGHT: Serendipity UUID % present — OK', v_serendipity_id;
END;
$$;

-- INSERT Cherokee Sunrise OPA (stripe_account_id = NULL — see header note)
INSERT INTO owner_payout_accounts (
    property_id,
    owner_name,
    owner_middle_name,
    owner_email,
    stripe_account_id,
    commission_rate,
    streamline_owner_id,
    mailing_address_line1,
    mailing_address_line2,
    mailing_address_city,
    mailing_address_state,
    mailing_address_postal_code,
    mailing_address_country,
    account_status,
    instant_payout,
    payout_schedule,
    minimum_payout_threshold,
    created_at,
    updated_at
) VALUES (
    '50a9066d-fc2e-44c4-a716-25adb8fbad3e',  -- Cherokee Sunrise
    'Gary Knight',
    'Mitchell',
    'gary@cabin-rentals-of-georgia.com',
    NULL,            -- stripe_account_id intentionally NULL (uq constraint; see header)
    0.3500,
    146514,
    'PO Box 982',
    NULL,
    'Morganton',
    'GA',
    '30560',
    'US',
    'pending_kyc',
    false,
    'monthly',
    100.00,
    now(),
    now()
)
ON CONFLICT (property_id) DO UPDATE
    SET owner_name                  = EXCLUDED.owner_name,
        owner_middle_name           = EXCLUDED.owner_middle_name,
        owner_email                 = EXCLUDED.owner_email,
        commission_rate             = EXCLUDED.commission_rate,
        streamline_owner_id         = EXCLUDED.streamline_owner_id,
        mailing_address_line1       = EXCLUDED.mailing_address_line1,
        mailing_address_city        = EXCLUDED.mailing_address_city,
        mailing_address_state       = EXCLUDED.mailing_address_state,
        mailing_address_postal_code = EXCLUDED.mailing_address_postal_code,
        mailing_address_country     = EXCLUDED.mailing_address_country,
        updated_at                  = now();

-- INSERT Serendipity OPA (stripe_account_id = NULL — see header note)
INSERT INTO owner_payout_accounts (
    property_id,
    owner_name,
    owner_middle_name,
    owner_email,
    stripe_account_id,
    commission_rate,
    streamline_owner_id,
    mailing_address_line1,
    mailing_address_line2,
    mailing_address_city,
    mailing_address_state,
    mailing_address_postal_code,
    mailing_address_country,
    account_status,
    instant_payout,
    payout_schedule,
    minimum_payout_threshold,
    created_at,
    updated_at
) VALUES (
    '63bf8847-9990-4a36-9943-b6c160ce1ec4',  -- Serendipity on Noontootla Creek
    'Gary Knight',
    'Mitchell',
    'gary@cabin-rentals-of-georgia.com',
    NULL,            -- stripe_account_id intentionally NULL (uq constraint; see header)
    0.3500,
    146514,
    'PO Box 982',
    NULL,
    'Morganton',
    'GA',
    '30560',
    'US',
    'pending_kyc',
    false,
    'monthly',
    100.00,
    now(),
    now()
)
ON CONFLICT (property_id) DO UPDATE
    SET owner_name                  = EXCLUDED.owner_name,
        owner_middle_name           = EXCLUDED.owner_middle_name,
        owner_email                 = EXCLUDED.owner_email,
        commission_rate             = EXCLUDED.commission_rate,
        streamline_owner_id         = EXCLUDED.streamline_owner_id,
        mailing_address_line1       = EXCLUDED.mailing_address_line1,
        mailing_address_city        = EXCLUDED.mailing_address_city,
        mailing_address_state       = EXCLUDED.mailing_address_state,
        mailing_address_postal_code = EXCLUDED.mailing_address_postal_code,
        mailing_address_country     = EXCLUDED.mailing_address_country,
        updated_at                  = now();

-- Post-insert verification
SELECT
    id,
    property_id,
    owner_name,
    owner_middle_name,
    commission_rate,
    streamline_owner_id,
    stripe_account_id,
    account_status
FROM owner_payout_accounts
WHERE property_id IN (
    '50a9066d-fc2e-44c4-a716-25adb8fbad3e',
    '63bf8847-9990-4a36-9943-b6c160ce1ec4',
    '93b2253d-7ae4-4d6f-8be2-125d33799c88'
)
ORDER BY property_id;
-- Expected: 3 rows, Gary Knight / Mitchell / 35% / sl_owner 146514
-- OPA 1824 (Fallen Timber): stripe_account_id = acct_...
-- New OPAs: stripe_account_id = NULL

COMMIT;
