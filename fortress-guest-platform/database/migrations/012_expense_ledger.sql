-- =============================================================================
-- Migration 012: Historical Expense Ledger Staging & Audit Archive
-- =============================================================================
-- Archives curated expenses from finance_invoices and Streamline work orders.
-- Links to Iron Dome journal_entries after the Expense Consumer commits them.
--
-- Depends on: 007_iron_dome_ledger.sql (journal_entries)
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS expense_events_archive (
    id                  SERIAL PRIMARY KEY,
    dedup_key           VARCHAR(255) UNIQUE NOT NULL,
    vendor_raw          TEXT NOT NULL,
    vendor_normalized   VARCHAR(255) NOT NULL,
    amount              DECIMAL(12, 2) NOT NULL,
    expense_date        DATE,
    category            VARCHAR(100),
    source              VARCHAR(50) NOT NULL,
    property_id         VARCHAR(50),
    journal_type        VARCHAR(50) NOT NULL,
    journal_entry_id    INT REFERENCES journal_entries(id),
    is_historical       BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eea_dedup    ON expense_events_archive(dedup_key);
CREATE INDEX IF NOT EXISTS idx_eea_vendor   ON expense_events_archive(vendor_normalized);
CREATE INDEX IF NOT EXISTS idx_eea_property ON expense_events_archive(property_id);
CREATE INDEX IF NOT EXISTS idx_eea_date     ON expense_events_archive(expense_date);

COMMIT;
