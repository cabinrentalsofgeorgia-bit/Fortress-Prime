-- Migration 013: Continuous Liquidity (Real-Time Owner Payouts)
--
-- owner_payout_accounts: Stores Stripe Connected Account IDs for each property
-- payout_ledger: Tracks every individual disbursement from trust to owner bank
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS owner_payout_accounts (
    id                  SERIAL PRIMARY KEY,
    property_id         TEXT NOT NULL UNIQUE,
    owner_name          TEXT,
    owner_email         TEXT,
    stripe_account_id   TEXT,
    account_status      TEXT DEFAULT 'pending'
                        CHECK (account_status IN (
                            'pending', 'onboarding', 'active', 'restricted', 'disabled'
                        )),
    instant_payout      BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payout_acct_property
    ON owner_payout_accounts(property_id);

CREATE TABLE IF NOT EXISTS payout_ledger (
    id                  SERIAL PRIMARY KEY,
    property_id         TEXT NOT NULL,
    confirmation_code   TEXT,
    journal_entry_id    INTEGER,
    gross_amount        NUMERIC(12,2) NOT NULL,
    owner_amount        NUMERIC(12,2) NOT NULL,
    stripe_transfer_id  TEXT,
    stripe_payout_id    TEXT,
    status              TEXT DEFAULT 'staged'
                        CHECK (status IN (
                            'staged', 'processing', 'completed', 'failed', 'manual'
                        )),
    initiated_at        TIMESTAMP,
    completed_at        TIMESTAMP,
    failure_reason      TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payout_ledger_property
    ON payout_ledger(property_id);
CREATE INDEX IF NOT EXISTS idx_payout_ledger_status
    ON payout_ledger(status);
CREATE INDEX IF NOT EXISTS idx_payout_ledger_conf_code
    ON payout_ledger(confirmation_code);

COMMIT;
