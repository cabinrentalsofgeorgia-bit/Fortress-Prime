-- =============================================================================
-- Migration 008: Owner Markup Rules — Automated PM Overhead Margin Capture
-- =============================================================================
-- Fortress Prime | Cabin Rentals of Georgia
--
-- This migration:
--   1. Upserts account 4100 as the PM Overhead revenue account
--   2. Creates the owner_markup_rules table (per-property, per-category margins)
--   3. Seeds a default 23% overhead rule for property 235641
--
-- The Trust Swarm's Ledger Coder uses these rules to execute a 3-Way GAAP Split:
--   DR 2000 (Total Charged to Owner)
--   CR 2100 (Vendor Cost — Accounts Payable)
--   CR 4100 (PM Overhead Profit)
-- =============================================================================

BEGIN;

-- 1. Upsert the Corporate Profit Account (4100 already seeded in 007 as
--    "Management Fee Revenue" — rename to reflect its expanded role)
INSERT INTO accounts (code, name, account_type, normal_balance, description)
VALUES ('4100', 'PM Overhead & Maintenance Revenue', 'Revenue', 'credit',
        'Property management overhead margin on owner-charged expenses')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- 2. Contract Rules Table — per-property markup percentages
CREATE TABLE IF NOT EXISTS owner_markup_rules (
    id                SERIAL PRIMARY KEY,
    property_id       TEXT NOT NULL,
    expense_category  VARCHAR(50) DEFAULT 'ALL',
    markup_percentage DECIMAL(5, 2) NOT NULL DEFAULT 23.00,
    created_at        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(property_id, expense_category),
    CONSTRAINT fk_markup_trust_balance
        FOREIGN KEY (property_id) REFERENCES trust_balance(property_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_omr_property ON owner_markup_rules(property_id);

-- 3. Seed default rule for property 235641 (23% overhead)
INSERT INTO owner_markup_rules (property_id, expense_category, markup_percentage)
VALUES ('235641', 'ALL', 23.00)
ON CONFLICT (property_id, expense_category)
DO UPDATE SET markup_percentage = EXCLUDED.markup_percentage;

COMMIT;
