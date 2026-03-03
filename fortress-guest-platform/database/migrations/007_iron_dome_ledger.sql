-- =============================================================================
-- Migration 007: Iron Dome Protocol — CF-04 GAAP Double-Entry Trust Accounting
-- =============================================================================
-- Fortress Prime | Cabin Rentals of Georgia
--
-- This migration:
--   1. Renames the legacy trust_balance snapshot table
--   2. Instantiates the CF-04 Audit Ledger (double-entry bookkeeping)
--   3. Arms the Iron Dome (debit==credit constraint trigger)
--   4. Enforces append-only immutability on journal_line_items
--   5. Seeds the GAAP Chart of Accounts (27 accounts)
--   6. Migrates existing balances as synthetic opening journal entries
--   7. Creates trust_balance_cache view for FGP frontend compatibility
--
-- IRON RULE: No transaction commits unless Debits == Credits.
-- FORTRESS PROTOCOL: journal_line_items is append-only (UPDATE/DELETE blocked).
-- =============================================================================

BEGIN;

-- =========================================================================
-- 1. PRESERVE LEGACY DATA
-- =========================================================================

ALTER TABLE IF EXISTS trust_balance RENAME TO trust_balance_legacy;

-- =========================================================================
-- 2. CHART OF ACCOUNTS
-- =========================================================================

CREATE TABLE IF NOT EXISTS accounts (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    account_type    TEXT NOT NULL CHECK (account_type IN (
                        'Asset', 'Liability', 'Equity', 'Revenue', 'Expense'
                    )),
    sub_type        TEXT,
    normal_balance  TEXT NOT NULL CHECK (normal_balance IN ('debit', 'credit')),
    parent_id       INTEGER REFERENCES accounts(id),
    property_id     TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_acct_type     ON accounts(account_type);
CREATE INDEX IF NOT EXISTS idx_acct_code     ON accounts(code);
CREATE INDEX IF NOT EXISTS idx_acct_property ON accounts(property_id);

-- =========================================================================
-- 3. JOURNAL ENTRIES (Transaction Headers)
-- =========================================================================

CREATE TABLE IF NOT EXISTS journal_entries (
    id              SERIAL PRIMARY KEY,
    entry_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    description     TEXT NOT NULL,
    reference_id    TEXT,
    reference_type  TEXT CHECK (reference_type IN (
                        'booking', 'invoice', 'payout', 'adjustment',
                        'cleaning_fee', 'tax_remittance', 'owner_draw',
                        'security_deposit', 'import', 'manual',
                        'trust_split', 'mgmt_fee', 'owner_deduction',
                        'owner_payout', 'tax_payment', NULL
                    )),
    property_id     TEXT,
    posted_by       TEXT DEFAULT 'system',
    source_system   TEXT DEFAULT 'fortress',
    is_void         BOOLEAN DEFAULT FALSE,
    void_reason     TEXT,
    voided_at       TIMESTAMP,
    voided_by       TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_je_date     ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_je_property ON journal_entries(property_id);
CREATE INDEX IF NOT EXISTS idx_je_ref      ON journal_entries(reference_id);
CREATE INDEX IF NOT EXISTS idx_je_ref_type ON journal_entries(reference_type);
CREATE INDEX IF NOT EXISTS idx_je_source   ON journal_entries(source_system);
CREATE INDEX IF NOT EXISTS idx_je_void     ON journal_entries(is_void);

-- =========================================================================
-- 4. JOURNAL LINE ITEMS (The Debits & Credits)
-- =========================================================================

CREATE TABLE IF NOT EXISTS journal_line_items (
    id                  SERIAL PRIMARY KEY,
    journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id          INTEGER NOT NULL REFERENCES accounts(id),
    debit               NUMERIC(15, 2) NOT NULL DEFAULT 0,
    credit              NUMERIC(15, 2) NOT NULL DEFAULT 0,
    memo                TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_single_side CHECK (
        (debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0)
    ),
    CONSTRAINT chk_non_negative CHECK (debit >= 0 AND credit >= 0)
);

CREATE INDEX IF NOT EXISTS idx_jli_entry   ON journal_line_items(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_jli_account ON journal_line_items(account_id);

-- =========================================================================
-- 5. IRON DOME: Balance Enforcement Trigger
-- =========================================================================
-- CONSTRAINT TRIGGER fires DEFERRED at end of transaction to verify
-- total debits == total credits for the journal entry.

CREATE OR REPLACE FUNCTION verify_journal_balance()
RETURNS TRIGGER AS $$
DECLARE
    total_debits    NUMERIC(15, 2);
    total_credits   NUMERIC(15, 2);
BEGIN
    SELECT
        COALESCE(SUM(debit), 0),
        COALESCE(SUM(credit), 0)
    INTO total_debits, total_credits
    FROM journal_line_items
    WHERE journal_entry_id = NEW.journal_entry_id;

    IF total_debits != total_credits THEN
        RAISE EXCEPTION
            '[IRON DOME] REJECTED: Entry #% — Debits ($%) != Credits ($%). Delta: $%',
            NEW.journal_entry_id,
            total_debits,
            total_credits,
            ABS(total_debits - total_credits);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_verify_balance
    AFTER INSERT OR UPDATE ON journal_line_items
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION verify_journal_balance();

-- =========================================================================
-- 6. FORTRESS PROTOCOL: Append-Only Ledger Enforcement
-- =========================================================================

CREATE OR REPLACE FUNCTION enforce_immutable_line_items()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'FORTRESS PROTOCOL: journal_line_items is append-only. Issue a reversing journal entry instead.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_immutable_line_items
BEFORE UPDATE OR DELETE ON journal_line_items
FOR EACH ROW EXECUTE FUNCTION enforce_immutable_line_items();

CREATE OR REPLACE FUNCTION enforce_journal_entry_integrity()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'FORTRESS PROTOCOL: journal_entries cannot be deleted. Use void to mark entries as void.';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.entry_date IS DISTINCT FROM NEW.entry_date
           OR OLD.description IS DISTINCT FROM NEW.description
           OR OLD.reference_id IS DISTINCT FROM NEW.reference_id
           OR OLD.reference_type IS DISTINCT FROM NEW.reference_type
           OR OLD.property_id IS DISTINCT FROM NEW.property_id
           OR OLD.posted_by IS DISTINCT FROM NEW.posted_by
           OR OLD.source_system IS DISTINCT FROM NEW.source_system THEN
            RAISE EXCEPTION 'FORTRESS PROTOCOL: Financial columns on journal_entries are immutable. Only void-related fields may be updated.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_journal_entry_integrity
BEFORE UPDATE OR DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION enforce_journal_entry_integrity();

-- =========================================================================
-- 7. TRUST BALANCE (Real-Time Owner vs. Operating Funds)
-- =========================================================================

CREATE TABLE IF NOT EXISTS trust_balance (
    id              SERIAL PRIMARY KEY,
    property_id     TEXT NOT NULL,
    owner_funds     NUMERIC(15, 2) NOT NULL DEFAULT 0,
    operating_funds NUMERIC(15, 2) NOT NULL DEFAULT 0,
    escrow_funds    NUMERIC(15, 2) NOT NULL DEFAULT 0,
    security_deps   NUMERIC(15, 2) NOT NULL DEFAULT 0,
    last_entry_id   INTEGER REFERENCES journal_entries(id),
    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_trust_property UNIQUE (property_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_property ON trust_balance(property_id);

-- =========================================================================
-- 8. ANOMALY FLAGS (AI-Detected Financial Anomalies)
-- =========================================================================

CREATE TABLE IF NOT EXISTS anomaly_flags (
    id                  SERIAL PRIMARY KEY,
    journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id),
    account_id          INTEGER REFERENCES accounts(id),
    flag_type           TEXT NOT NULL CHECK (flag_type IN (
                            'amount_deviation', 'unusual_category', 'duplicate_suspect',
                            'missing_reference', 'trust_imbalance', 'manual_review'
                        )),
    severity            TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    deviation_pct       NUMERIC(8, 2),
    expected_amount     NUMERIC(15, 2),
    actual_amount       NUMERIC(15, 2),
    ai_explanation      TEXT,
    reviewed            BOOLEAN DEFAULT FALSE,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMP,
    review_notes        TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_af_entry    ON anomaly_flags(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_af_type     ON anomaly_flags(flag_type);
CREATE INDEX IF NOT EXISTS idx_af_severity ON anomaly_flags(severity);
CREATE INDEX IF NOT EXISTS idx_af_reviewed ON anomaly_flags(reviewed);

-- =========================================================================
-- 9. VIEWS: Live Financial Intelligence
-- =========================================================================

CREATE OR REPLACE VIEW v_trial_balance AS
SELECT
    a.id AS account_id,
    a.code,
    a.name AS account_name,
    a.account_type,
    a.normal_balance,
    COALESCE(SUM(jli.debit), 0) AS total_debits,
    COALESCE(SUM(jli.credit), 0) AS total_credits,
    COALESCE(SUM(jli.debit), 0) - COALESCE(SUM(jli.credit), 0) AS net_balance
FROM accounts a
LEFT JOIN journal_line_items jli ON jli.account_id = a.id
LEFT JOIN journal_entries je ON je.id = jli.journal_entry_id AND je.is_void = FALSE
WHERE a.is_active = TRUE
GROUP BY a.id, a.code, a.name, a.account_type, a.normal_balance
ORDER BY a.code;

CREATE OR REPLACE VIEW v_trust_summary AS
SELECT
    property_id,
    owner_funds,
    operating_funds,
    escrow_funds,
    security_deps,
    (owner_funds + operating_funds + escrow_funds + security_deps) AS total_funds,
    last_updated
FROM trust_balance
ORDER BY property_id;

CREATE OR REPLACE VIEW v_journal_detail AS
SELECT
    je.id AS entry_id,
    je.entry_date,
    je.description,
    je.reference_id,
    je.reference_type,
    je.property_id,
    je.posted_by,
    je.source_system,
    je.is_void,
    jli.id AS line_id,
    a.code AS account_code,
    a.name AS account_name,
    a.account_type,
    jli.debit,
    jli.credit,
    jli.memo,
    je.created_at
FROM journal_entries je
JOIN journal_line_items jli ON jli.journal_entry_id = je.id
JOIN accounts a ON a.id = jli.account_id
ORDER BY je.entry_date DESC, je.id, jli.id;

-- =========================================================================
-- 10. SEED: GAAP Chart of Accounts for Property Management
-- =========================================================================

INSERT INTO accounts (code, name, account_type, sub_type, normal_balance, description)
SELECT * FROM (VALUES
    -- ASSETS (Normal Balance: Debit)
    ('1000', 'Cash - Operating',            'Asset',     'Operating',  'debit',  'Main operating bank account'),
    ('1010', 'Cash - Trust',                'Asset',     'Trust',      'debit',  'Trust/escrow account for owner funds'),
    ('1020', 'Cash - Security Deposits',    'Asset',     'Escrow',     'debit',  'Guest security deposit holding'),
    ('1100', 'Accounts Receivable',         'Asset',     'Operating',  'debit',  'Outstanding guest payments'),
    ('1200', 'Prepaid Expenses',            'Asset',     'Operating',  'debit',  'Advance payments for services'),

    -- LIABILITIES (Normal Balance: Credit)
    ('2000', 'Trust Liability - Owners',    'Liability', 'Trust',      'credit', 'Funds owed to property owners'),
    ('2010', 'Security Deposit Liability',  'Liability', 'Escrow',     'credit', 'Refundable guest security deposits'),
    ('2100', 'Accounts Payable',            'Liability', 'Operating',  'credit', 'Outstanding vendor invoices'),
    ('2200', 'Sales Tax Payable',           'Liability', 'Tax',        'credit', 'Collected sales/occupancy tax'),
    ('2210', 'Occupancy Tax Payable',       'Liability', 'Tax',        'credit', 'County/state lodging tax'),
    ('2300', 'Deferred Revenue',            'Liability', 'Operating',  'credit', 'Advance booking payments not yet earned'),

    -- EQUITY (Normal Balance: Credit)
    ('3000', 'Owner Equity',                'Equity',    'Operating',  'credit', 'Company owner equity'),
    ('3100', 'Retained Earnings',           'Equity',    'Operating',  'credit', 'Accumulated net income'),

    -- REVENUE (Normal Balance: Credit)
    ('4000', 'Rental Revenue',              'Revenue',   'Operating',  'credit', 'Cabin rental income'),
    ('4010', 'Cleaning Fee Revenue',        'Revenue',   'Operating',  'credit', 'Guest cleaning fees collected'),
    ('4020', 'Pet Fee Revenue',             'Revenue',   'Operating',  'credit', 'Pet fees collected'),
    ('4030', 'Late Fee Revenue',            'Revenue',   'Operating',  'credit', 'Late checkout/payment fees'),
    ('4100', 'Management Fee Revenue',      'Revenue',   'Operating',  'credit', 'Property management commissions'),
    ('4200', 'Other Income',                'Revenue',   'Operating',  'credit', 'Miscellaneous income'),

    -- EXPENSES (Normal Balance: Debit)
    ('5000', 'Cleaning Expense',            'Expense',   'Operating',  'debit',  'Cleaning service costs'),
    ('5010', 'Maintenance & Repairs',       'Expense',   'Operating',  'debit',  'Property maintenance costs'),
    ('5020', 'Utilities',                   'Expense',   'Operating',  'debit',  'Electric, water, gas, internet'),
    ('5030', 'Supplies',                    'Expense',   'Operating',  'debit',  'Guest supplies, toiletries, linens'),
    ('5040', 'Insurance',                   'Expense',   'Operating',  'debit',  'Property insurance premiums'),
    ('5050', 'Property Tax',                'Expense',   'Operating',  'debit',  'County property taxes'),
    ('5060', 'Advertising & Marketing',     'Expense',   'Operating',  'debit',  'Listing fees, ad spend'),
    ('5070', 'Software & Technology',       'Expense',   'Operating',  'debit',  'PMS, channel manager, tools'),
    ('5080', 'Professional Fees',           'Expense',   'Operating',  'debit',  'Legal, accounting, consulting'),
    ('5090', 'Payroll',                     'Expense',   'Operating',  'debit',  'Staff wages and benefits'),
    ('5100', 'Commission Expense',          'Expense',   'Operating',  'debit',  'Booking platform commissions'),
    ('5200', 'Owner Payout',               'Expense',   'Operating',  'debit',  'Distributions to property owners'),
    ('5900', 'Miscellaneous Expense',       'Expense',   'Operating',  'debit',  'Uncategorized expenses')
) AS seed(code, name, account_type, sub_type, normal_balance, description)
WHERE NOT EXISTS (SELECT 1 FROM accounts LIMIT 1);

-- =========================================================================
-- 11. MIGRATE LEGACY BALANCES AS OPENING JOURNAL ENTRIES
-- =========================================================================
-- Each legacy property gets a balanced opening entry:
--   DR Cash - Trust (1010)     = owner_funds
--   CR Trust Liability (2000)  = owner_funds
-- This records the existing owner funds as a proper double-entry.

DO $$
DECLARE
    legacy RECORD;
    entry_id INTEGER;
    acct_1010 INTEGER;
    acct_2000 INTEGER;
BEGIN
    SELECT id INTO acct_1010 FROM accounts WHERE code = '1010';
    SELECT id INTO acct_2000 FROM accounts WHERE code = '2000';

    IF acct_1010 IS NULL OR acct_2000 IS NULL THEN
        RAISE NOTICE 'Seed accounts not found — skipping legacy migration.';
        RETURN;
    END IF;

    FOR legacy IN SELECT * FROM trust_balance_legacy LOOP
        IF legacy.owner_funds IS NOT NULL AND legacy.owner_funds != 0 THEN
            INSERT INTO journal_entries (
                entry_date, description, reference_id, reference_type,
                property_id, posted_by, source_system
            ) VALUES (
                CURRENT_DATE,
                'Opening balance — migrated from Layer 1 snapshot',
                legacy.property_id,
                'import',
                legacy.property_id,
                'migration_007',
                'streamline_import'
            ) RETURNING id INTO entry_id;

            INSERT INTO journal_line_items (journal_entry_id, account_id, debit, credit, memo)
            VALUES
                (entry_id, acct_1010, legacy.owner_funds, 0, 'Opening trust fund balance'),
                (entry_id, acct_2000, 0, legacy.owner_funds, 'Opening trust liability to owner');
        END IF;

        INSERT INTO trust_balance (
            property_id, owner_funds, operating_funds, escrow_funds,
            security_deps, last_entry_id, last_updated
        ) VALUES (
            legacy.property_id,
            COALESCE(legacy.owner_funds, 0),
            COALESCE(legacy.operating_funds, 0),
            COALESCE(legacy.escrow_funds, 0),
            COALESCE(legacy.security_deps, 0),
            entry_id,
            COALESCE(legacy.last_updated, CURRENT_TIMESTAMP)
        );
    END LOOP;
END $$;

-- =========================================================================
-- 12. READ-ONLY CACHE VIEW (FGP Frontend Compatibility)
-- =========================================================================
-- The owner_portal.py endpoint reads from this view instead of the table
-- directly. Same columns, same interface, zero frontend code changes.

CREATE OR REPLACE VIEW trust_balance_cache AS
SELECT
    property_id,
    owner_funds,
    operating_funds,
    escrow_funds,
    security_deps,
    last_updated
FROM trust_balance;

-- =========================================================================
-- DONE: Iron Dome is armed. CF-04 Audit Ledger is the canonical trust vault.
-- =========================================================================

COMMIT;
