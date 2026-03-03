-- Migration 009: CapEx Staging Table
-- Stores high-ticket invoices (>= $500) that require owner approval
-- before the Trust Swarm commits them to the Iron Dome ledger.

CREATE TABLE IF NOT EXISTS capex_staging (
    id                  SERIAL PRIMARY KEY,
    property_id         TEXT NOT NULL,
    vendor              TEXT NOT NULL,
    amount              NUMERIC(15, 2) NOT NULL,
    total_owner_charge  NUMERIC(15, 2) NOT NULL,
    description         TEXT,
    journal_lines       JSONB NOT NULL,
    compliance_status   TEXT DEFAULT 'PENDING_CAPEX_APPROVAL'
                        CHECK (compliance_status IN (
                            'PENDING_CAPEX_APPROVAL',
                            'APPROVED',
                            'REJECTED'
                        )),
    audit_trail         JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_by         TEXT,
    approved_at         TIMESTAMP,
    rejected_by         TEXT,
    rejected_at         TIMESTAMP,
    rejection_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_capex_staging_property
    ON capex_staging (property_id);
CREATE INDEX IF NOT EXISTS idx_capex_staging_status
    ON capex_staging (compliance_status);
