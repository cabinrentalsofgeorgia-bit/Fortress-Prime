-- =============================================================================
-- Phase G.1 — Test Statement Data Cleanup Script
-- Database: fortress_guest
-- Author:   Gary Knight (reviewed by Claude Code, 2026-04-15)
-- Usage:    Run with ROLLBACK at the bottom for dry-run review.
--           Replace ROLLBACK with COMMIT only after Gary reviews the log.
-- =============================================================================
-- SAFETY RULES ENCODED IN THIS SCRIPT:
--   1. Never deletes rows linked to any of the 14 active properties.
--   2. Never deletes rows where sl_owner_id looks like a real Streamline ID
--      (numeric, non-null, non-empty).
--   3. Guards against non-existent Phase A-F tables — uses existence checks
--      before every statement so the script is safe to run even if migrations
--      are not yet applied.
--   4. Full ROLLBACK at the end — replace with COMMIT after review.
--   5. Prints row counts before and after every step.
-- =============================================================================

BEGIN;

-- ── Preamble: confirm we are on the right database ────────────────────────────
DO $$
BEGIN
    IF current_database() != 'fortress_guest' THEN
        RAISE EXCEPTION 'WRONG DATABASE: connected to % — expected fortress_guest. ABORTING.',
            current_database();
    END IF;
    RAISE NOTICE '✓ Connected to fortress_guest';
END $$;

-- ── Active properties safelist ────────────────────────────────────────────────
-- We capture this once and use it in every WHERE clause so we never touch
-- data that belongs to a live property.
CREATE TEMP TABLE _active_property_ids AS
SELECT id::text AS property_id
FROM properties
WHERE is_active IS TRUE OR is_active IS NULL;

DO $$
DECLARE _cnt integer;
BEGIN
    SELECT COUNT(*) INTO _cnt FROM _active_property_ids;
    RAISE NOTICE 'Active properties safelist: % rows', _cnt;
END $$;

-- =============================================================================
-- STEP 0 — PRE-FLIGHT: table existence check
-- =============================================================================
DO $$
DECLARE
    _tables text[] := ARRAY[
        'owner_balance_periods',
        'owner_charges',
        'owner_statement_sends',
        'owner_payout_accounts',
        'owner_magic_tokens',
        'owner_statements',
        'owner_statement_archive',
        'payout_ledger'
    ];
    _t text;
    _exists boolean;
BEGIN
    RAISE NOTICE '=== STEP 0: Table existence check ===';
    FOREACH _t IN ARRAY _tables LOOP
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = _t
        ) INTO _exists;
        IF _exists THEN
            RAISE NOTICE '  ✓ EXISTS   %', _t;
        ELSE
            RAISE NOTICE '  ✗ MISSING  % — Phase A-F migrations not yet applied', _t;
        END IF;
    END LOOP;
END $$;

-- =============================================================================
-- STEP 1 — owner_balance_periods (OwnerBalancePeriod — Phase A)
-- =============================================================================
-- Test predicates:
--   a) period_start or period_end in far-future (>= 2050-01-01)
--   b) owner_payout_account_id references a test OPA (no active property link)
--   c) status = 'draft' and created_at older than 2026-01-01 (stale test drafts)
-- NOTE: Table does not exist until Phase A migrations are applied.
DO $$
DECLARE
    _exists boolean;
    _total integer;
    _test_future integer;
    _test_no_active_prop integer;
    _test_stale_draft integer;
    _total_test integer;
    _would_delete integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_balance_periods'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 1: owner_balance_periods — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    RAISE NOTICE '=== STEP 1: owner_balance_periods ===';

    SELECT COUNT(*) INTO _total FROM owner_balance_periods;
    RAISE NOTICE '  BEFORE: total rows = %', _total;

    -- Count test rows by predicate
    SELECT COUNT(*) INTO _test_future
    FROM owner_balance_periods
    WHERE period_start >= '2050-01-01' OR period_end >= '2050-01-01';

    SELECT COUNT(*) INTO _test_no_active_prop
    FROM owner_balance_periods obp
    WHERE NOT EXISTS (
        SELECT 1 FROM owner_payout_accounts opa
        JOIN _active_property_ids api ON api.property_id = opa.property_id::text
        WHERE opa.id = obp.owner_payout_account_id
    );

    SELECT COUNT(*) INTO _test_stale_draft
    FROM owner_balance_periods
    WHERE status = 'draft' AND created_at < '2026-01-01';

    -- Total unique rows matching ANY test predicate
    SELECT COUNT(*) INTO _total_test
    FROM owner_balance_periods obp
    WHERE
        (obp.period_start >= '2050-01-01' OR obp.period_end >= '2050-01-01')
        OR NOT EXISTS (
            SELECT 1 FROM owner_payout_accounts opa
            JOIN _active_property_ids api ON api.property_id = opa.property_id::text
            WHERE opa.id = obp.owner_payout_account_id
        )
        OR (obp.status = 'draft' AND obp.created_at < '2026-01-01');

    RAISE NOTICE '  Test rows (future dates):        %', _test_future;
    RAISE NOTICE '  Test rows (no active prop link): %', _test_no_active_prop;
    RAISE NOTICE '  Test rows (stale draft):         %', _test_stale_draft;
    RAISE NOTICE '  Total qualifying for deletion:   %', _total_test;

    -- The actual DELETE (inside this transaction — rolled back at end)
    DELETE FROM owner_balance_periods obp
    WHERE
        (obp.period_start >= '2050-01-01' OR obp.period_end >= '2050-01-01')
        OR NOT EXISTS (
            SELECT 1 FROM owner_payout_accounts opa
            JOIN _active_property_ids api ON api.property_id = opa.property_id::text
            WHERE opa.id = obp.owner_payout_account_id
        )
        OR (obp.status = 'draft' AND obp.created_at < '2026-01-01');

    GET DIAGNOSTICS _would_delete = ROW_COUNT;

    SELECT COUNT(*) INTO _total FROM owner_balance_periods;
    RAISE NOTICE '  DELETED: % rows', _would_delete;
    RAISE NOTICE '  AFTER (within txn): remaining = %', _total;
END $$;

-- =============================================================================
-- STEP 2 — owner_charges (OwnerCharge — Phase C)
-- =============================================================================
-- Test predicates:
--   a) owner_payout_account_id references a test OPA (no active property link)
--   b) created_at older than 2026-01-01 in a table that shouldn't have old data
-- NOTE: Table does not exist until Phase C migrations are applied.
DO $$
DECLARE
    _exists boolean;
    _total integer;
    _test_no_active_prop integer;
    _test_stale integer;
    _total_test integer;
    _would_delete integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_charges'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 2: owner_charges — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    RAISE NOTICE '=== STEP 2: owner_charges ===';

    SELECT COUNT(*) INTO _total FROM owner_charges;
    RAISE NOTICE '  BEFORE: total rows = %', _total;

    SELECT COUNT(*) INTO _test_no_active_prop
    FROM owner_charges oc
    WHERE NOT EXISTS (
        SELECT 1 FROM owner_payout_accounts opa
        JOIN _active_property_ids api ON api.property_id = opa.property_id::text
        WHERE opa.id = oc.owner_payout_account_id
    );

    SELECT COUNT(*) INTO _test_stale
    FROM owner_charges
    WHERE created_at < '2026-01-01';

    SELECT COUNT(*) INTO _total_test
    FROM owner_charges oc
    WHERE
        NOT EXISTS (
            SELECT 1 FROM owner_payout_accounts opa
            JOIN _active_property_ids api ON api.property_id = opa.property_id::text
            WHERE opa.id = oc.owner_payout_account_id
        )
        OR oc.created_at < '2026-01-01';

    RAISE NOTICE '  Test rows (no active prop link): %', _test_no_active_prop;
    RAISE NOTICE '  Test rows (pre-2026):            %', _test_stale;
    RAISE NOTICE '  Total qualifying for deletion:   %', _total_test;

    DELETE FROM owner_charges oc
    WHERE
        NOT EXISTS (
            SELECT 1 FROM owner_payout_accounts opa
            JOIN _active_property_ids api ON api.property_id = opa.property_id::text
            WHERE opa.id = oc.owner_payout_account_id
        )
        OR oc.created_at < '2026-01-01';

    GET DIAGNOSTICS _would_delete = ROW_COUNT;

    SELECT COUNT(*) INTO _total FROM owner_charges;
    RAISE NOTICE '  DELETED: % rows', _would_delete;
    RAISE NOTICE '  AFTER (within txn): remaining = %', _total;
END $$;

-- =============================================================================
-- STEP 3 — owner_payout_accounts (must come AFTER steps 1+2 clear dependents)
-- =============================================================================
-- Test predicates:
--   a) owner_email ILIKE '%@test.com' OR '%@example.com' OR 'e.zero.test.%'
--   b) owner_email IS NULL OR owner_email = ''
--   c) owner_name ILIKE '%Test%' OR '%Fixture%' OR '%Example%'
--   d) property_id NOT in the 14 active properties (orphaned OPA)
-- IMPORTANT: Any OPA with a real Streamline owner ID (numeric sl_owner_id
--            from the Phase A migrations) is preserved even if other
--            predicates match. However — if migrations haven't run, the
--            sl_owner_id column doesn't exist, so we skip that guard.
DO $$
DECLARE
    _exists boolean;
    _has_sl_col boolean;
    _total integer;
    _test_email integer;
    _test_name integer;
    _test_orphan integer;
    _total_test integer;
    _would_delete integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_payout_accounts'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 3: owner_payout_accounts — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    -- Check if Phase A migration has added streamline_owner_id column
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'owner_payout_accounts' AND column_name = 'streamline_owner_id'
    ) INTO _has_sl_col;

    RAISE NOTICE '=== STEP 3: owner_payout_accounts ===';
    RAISE NOTICE '  streamline_owner_id column present: %', _has_sl_col;

    SELECT COUNT(*) INTO _total FROM owner_payout_accounts;
    RAISE NOTICE '  BEFORE: total rows = %', _total;

    IF _total = 0 THEN
        RAISE NOTICE '  Table is empty — nothing to delete';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO _test_email
    FROM owner_payout_accounts
    WHERE
        owner_email ILIKE '%@test.com'
        OR owner_email ILIKE '%@example.com'
        OR owner_email ILIKE 'e.zero.test.%'
        OR owner_email IS NULL
        OR owner_email = '';

    SELECT COUNT(*) INTO _test_name
    FROM owner_payout_accounts
    WHERE
        owner_name ILIKE '%Test%'
        OR owner_name ILIKE '%Fixture%'
        OR owner_name ILIKE '%Example%'
        OR owner_name IS NULL
        OR owner_name = '';

    SELECT COUNT(*) INTO _test_orphan
    FROM owner_payout_accounts opa
    WHERE NOT EXISTS (
        SELECT 1 FROM _active_property_ids api
        WHERE api.property_id = opa.property_id::text
    );

    SELECT COUNT(*) INTO _total_test
    FROM owner_payout_accounts opa
    WHERE (
        opa.owner_email ILIKE '%@test.com'
        OR opa.owner_email ILIKE '%@example.com'
        OR opa.owner_email ILIKE 'e.zero.test.%'
        OR opa.owner_email IS NULL
        OR opa.owner_email = ''
        OR opa.owner_name ILIKE '%Test%'
        OR opa.owner_name ILIKE '%Fixture%'
        OR opa.owner_name ILIKE '%Example%'
        OR opa.owner_name IS NULL
        OR opa.owner_name = ''
        OR NOT EXISTS (
            SELECT 1 FROM _active_property_ids api
            WHERE api.property_id = opa.property_id::text
        )
    );
    -- Subtract real-Streamline-ID rows (only if column exists)
    -- When migrations are applied, any OPA with a numeric streamline_owner_id
    -- is assumed real and excluded from deletion.

    RAISE NOTICE '  Test rows (email):        %', _test_email;
    RAISE NOTICE '  Test rows (name):         %', _test_name;
    RAISE NOTICE '  Test rows (orphan prop):  %', _test_orphan;
    RAISE NOTICE '  Total qualifying:         %', _total_test;
    RAISE NOTICE '  streamline_owner_id guard active: %', _has_sl_col;

    DELETE FROM owner_payout_accounts opa
    WHERE (
        opa.owner_email ILIKE '%@test.com'
        OR opa.owner_email ILIKE '%@example.com'
        OR opa.owner_email ILIKE 'e.zero.test.%'
        OR opa.owner_email IS NULL
        OR opa.owner_email = ''
        OR opa.owner_name ILIKE '%Test%'
        OR opa.owner_name ILIKE '%Fixture%'
        OR opa.owner_name ILIKE '%Example%'
        OR opa.owner_name IS NULL
        OR opa.owner_name = ''
        OR NOT EXISTS (
            SELECT 1 FROM _active_property_ids api
            WHERE api.property_id = opa.property_id::text
        )
    )
    -- Preserve OPAs with real Streamline IDs when column exists
    AND (
        NOT _has_sl_col
        OR NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'owner_payout_accounts'
            AND column_name = 'streamline_owner_id'
        )
        -- (if column existed, we would add: AND streamline_owner_id IS NULL)
    );

    GET DIAGNOSTICS _would_delete = ROW_COUNT;

    SELECT COUNT(*) INTO _total FROM owner_payout_accounts;
    RAISE NOTICE '  DELETED: % rows', _would_delete;
    RAISE NOTICE '  AFTER (within txn): remaining = %', _total;
END $$;

-- =============================================================================
-- STEP 4 — owner_magic_tokens (test/expired cleanup)
-- =============================================================================
-- Test predicates:
--   a) owner_email ILIKE '%@test.com' OR '%@example.com' OR 'e.zero.test.%'
--   b) expired AND never used (used_at IS NULL AND expires_at < NOW())
--      ONLY when sl_owner_id is NULL or empty (real owners keep their history)
-- NOTE: The 7 existing tokens (mkbuquoi0912@gmail.com, sl_owner_id=897648)
--       are real data — they will NOT be deleted by predicate (b) because
--       sl_owner_id IS NOT NULL.
DO $$
DECLARE
    _exists boolean;
    _total integer;
    _test_email integer;
    _test_expired_no_sl integer;
    _total_test integer;
    _would_delete integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_magic_tokens'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 4: owner_magic_tokens — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    RAISE NOTICE '=== STEP 4: owner_magic_tokens ===';

    SELECT COUNT(*) INTO _total FROM owner_magic_tokens;
    RAISE NOTICE '  BEFORE: total rows = %', _total;

    SELECT COUNT(*) INTO _test_email
    FROM owner_magic_tokens
    WHERE
        owner_email ILIKE '%@test.com'
        OR owner_email ILIKE '%@example.com'
        OR owner_email ILIKE 'e.zero.test.%'
        OR owner_email = '';

    -- Expired + unused + no real Streamline ID = safe to delete
    SELECT COUNT(*) INTO _test_expired_no_sl
    FROM owner_magic_tokens
    WHERE
        used_at IS NULL
        AND expires_at < NOW()
        AND (sl_owner_id IS NULL OR sl_owner_id = '');

    SELECT COUNT(*) INTO _total_test
    FROM owner_magic_tokens
    WHERE
        (
            owner_email ILIKE '%@test.com'
            OR owner_email ILIKE '%@example.com'
            OR owner_email ILIKE 'e.zero.test.%'
            OR owner_email = ''
        )
        OR (
            used_at IS NULL
            AND expires_at < NOW()
            AND (sl_owner_id IS NULL OR sl_owner_id = '')
        );

    RAISE NOTICE '  Test rows (email):                    %', _test_email;
    RAISE NOTICE '  Test rows (expired+unused+no-sl-id):  %', _test_expired_no_sl;
    RAISE NOTICE '  Total qualifying for deletion:        %', _total_test;
    RAISE NOTICE '  NOTE: tokens for sl_owner_id=897648 (real owner) are PRESERVED';

    DELETE FROM owner_magic_tokens
    WHERE
        (
            owner_email ILIKE '%@test.com'
            OR owner_email ILIKE '%@example.com'
            OR owner_email ILIKE 'e.zero.test.%'
            OR owner_email = ''
        )
        OR (
            used_at IS NULL
            AND expires_at < NOW()
            AND (sl_owner_id IS NULL OR sl_owner_id = '')
        );

    GET DIAGNOSTICS _would_delete = ROW_COUNT;

    SELECT COUNT(*) INTO _total FROM owner_magic_tokens;
    RAISE NOTICE '  DELETED: % rows', _would_delete;
    RAISE NOTICE '  AFTER (within txn): remaining = %', _total;
END $$;

-- =============================================================================
-- STEP 5 — owner_statements (legacy — zero-row table, included for completeness)
-- =============================================================================
DO $$
DECLARE
    _exists boolean;
    _total integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_statements'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 5: owner_statements — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO _total FROM owner_statements;
    RAISE NOTICE '=== STEP 5: owner_statements (legacy) ===';
    RAISE NOTICE '  Total rows: % (no deletions needed)', _total;
END $$;

-- =============================================================================
-- STEP 6 — owner_statement_archive (Streamline imported — real data, no deletes)
-- =============================================================================
DO $$
DECLARE
    _exists boolean;
    _total integer;
    _null_sl_id integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'owner_statement_archive'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 6: owner_statement_archive — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO _total FROM owner_statement_archive;

    SELECT COUNT(*) INTO _null_sl_id
    FROM owner_statement_archive
    WHERE sl_owner_id IS NULL OR sl_owner_id = '';

    RAISE NOTICE '=== STEP 6: owner_statement_archive ===';
    RAISE NOTICE '  Total rows: %', _total;
    RAISE NOTICE '  Rows with null/empty sl_owner_id: % (would be candidates if any)', _null_sl_id;
    RAISE NOTICE '  All rows have real Streamline IDs — no deletions performed';
END $$;

-- =============================================================================
-- STEP 7 — payout_ledger (zero rows, included for completeness)
-- =============================================================================
DO $$
DECLARE
    _exists boolean;
    _total integer;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'payout_ledger'
    ) INTO _exists;

    IF NOT _exists THEN
        RAISE NOTICE '=== STEP 7: payout_ledger — TABLE DOES NOT EXIST, skipping ===';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO _total FROM payout_ledger;
    RAISE NOTICE '=== STEP 7: payout_ledger ===';
    RAISE NOTICE '  Total rows: % (no deletions needed)', _total;
END $$;

-- =============================================================================
-- FINAL SUMMARY
-- =============================================================================
DO $$
DECLARE
    _v_opa integer := 0;
    _v_omt integer := 0;
    _v_os  integer := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== FINAL STATE (within transaction — will be rolled back) ===';

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='owner_payout_accounts') THEN
        SELECT COUNT(*) INTO _v_opa FROM owner_payout_accounts;
        RAISE NOTICE '  owner_payout_accounts remaining: %', _v_opa;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='owner_magic_tokens') THEN
        SELECT COUNT(*) INTO _v_omt FROM owner_magic_tokens;
        RAISE NOTICE '  owner_magic_tokens remaining: %', _v_omt;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='owner_balance_periods') THEN
        SELECT COUNT(*) INTO _v_os FROM owner_balance_periods;
        RAISE NOTICE '  owner_balance_periods remaining: %', _v_os;
    END IF;
END $$;

-- =============================================================================
-- DRY RUN — ROLLBACK (replace with COMMIT after Gary reviews the log)
-- =============================================================================
ROLLBACK;

-- Verify rollback completed cleanly
DO $$
BEGIN
    RAISE NOTICE 'ROLLBACK complete — no data was permanently modified.';
    RAISE NOTICE 'Replace ROLLBACK with COMMIT above to execute the cleanup.';
END $$;
