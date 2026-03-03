-- Migration 010: Management Splits Table
-- Stores per-property owner/PM revenue split percentages.
-- The Revenue Consumer Daemon looks up splits here to determine
-- how to journal reservation income between owner trust liability
-- and PM commission revenue.

CREATE TABLE IF NOT EXISTS management_splits (
    id              SERIAL PRIMARY KEY,
    property_id     TEXT NOT NULL UNIQUE,
    owner_pct       NUMERIC(5, 2) NOT NULL DEFAULT 65.00,
    pm_pct          NUMERIC(5, 2) NOT NULL DEFAULT 35.00,
    effective_date  DATE DEFAULT CURRENT_DATE,
    CONSTRAINT chk_split_total CHECK (owner_pct + pm_pct = 100.00)
);

-- Seed default 65/35 split for all properties currently in trust_balance_cache
INSERT INTO management_splits (property_id, owner_pct, pm_pct)
SELECT property_id, 65.00, 35.00
FROM trust_balance_cache
ON CONFLICT (property_id) DO NOTHING;
