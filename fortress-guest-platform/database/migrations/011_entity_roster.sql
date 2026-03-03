-- =============================================================================
-- Migration 011: Entity Roster — Owner/Property Cross-Reference & Statement Archive
-- =============================================================================
-- Links Streamline owner_ids to unit_ids (property_ids) and archives raw
-- monthly statement metadata/PDFs from Streamline for reconciliation.
--
-- Depends on: 007_iron_dome_ledger.sql (trust_balance), 010_management_splits.sql
-- =============================================================================

BEGIN;

-- 1. Owner-to-Property cross-reference from Streamline's GetOwnerList.
--    One owner can have many properties (Gary Knight = 14+), so PK is composite.
CREATE TABLE IF NOT EXISTS owner_property_map (
    id              SERIAL PRIMARY KEY,
    sl_owner_id     TEXT NOT NULL,
    unit_id         TEXT NOT NULL,
    owner_name      TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    property_name   TEXT NOT NULL,
    live_balance    DECIMAL(12, 2) DEFAULT 0.00,
    synced_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sl_owner_id, unit_id)
);

CREATE INDEX IF NOT EXISTS idx_opm_unit     ON owner_property_map(unit_id);
CREATE INDEX IF NOT EXISTS idx_opm_owner    ON owner_property_map(sl_owner_id);

-- 2. Raw Streamline statement archive for reconciliation and future PDF parsing.
CREATE TABLE IF NOT EXISTS owner_statement_archive (
    id                      SERIAL PRIMARY KEY,
    streamline_statement_id TEXT,
    sl_owner_id             TEXT NOT NULL,
    unit_id                 TEXT NOT NULL,
    period_start            DATE NOT NULL,
    period_end              DATE NOT NULL,
    pdf_path                TEXT,
    extracted_data          JSONB,
    archived_at             TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sl_owner_id, unit_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_osa_owner_unit ON owner_statement_archive(sl_owner_id, unit_id);
CREATE INDEX IF NOT EXISTS idx_osa_period     ON owner_statement_archive(period_start, period_end);

COMMIT;
