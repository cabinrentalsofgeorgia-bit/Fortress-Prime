-- ============================================================================
-- Migration 002: Trust Accounting Extensions
-- Creates trust balance tracking and owner statement tables
-- (The full chart of accounts lives in CF-04 AuditLedger's own schema)
-- ============================================================================

BEGIN;

-- Owner statements table (generated monthly)
CREATE TABLE IF NOT EXISTS owner_statements (
    id SERIAL PRIMARY KEY,
    property_id VARCHAR(100) NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    booking_count INTEGER DEFAULT 0,
    gross_revenue DECIMAL(12,2) DEFAULT 0,
    cleaning_revenue DECIMAL(12,2) DEFAULT 0,
    management_fee DECIMAL(12,2) DEFAULT 0,
    tax_escrow DECIMAL(12,2) DEFAULT 0,
    maintenance_expenses DECIMAL(12,2) DEFAULT 0,
    net_to_owner DECIMAL(12,2) DEFAULT 0,
    payout_amount DECIMAL(12,2) DEFAULT 0,
    payout_status VARCHAR(20) DEFAULT 'pending',
    payout_date DATE,
    payout_method VARCHAR(50),
    payout_reference VARCHAR(100),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(property_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_owner_statements_property ON owner_statements(property_id);
CREATE INDEX IF NOT EXISTS idx_owner_statements_period ON owner_statements(period_start, period_end);

-- Trust balance snapshot (per property, updated on each transaction)
CREATE TABLE IF NOT EXISTS trust_balance (
    property_id VARCHAR(100) PRIMARY KEY,
    owner_funds DECIMAL(12,2) DEFAULT 0,
    operating_funds DECIMAL(12,2) DEFAULT 0,
    escrow_funds DECIMAL(12,2) DEFAULT 0,
    security_deps DECIMAL(12,2) DEFAULT 0,
    last_entry_id INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
