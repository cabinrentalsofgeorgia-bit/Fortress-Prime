-- FORTRESS PRIME — Deliberation Events Migration
-- ================================================
-- Verifiable Intelligence Engine: Event Sourcing with Cryptographic Provenance
-- for the Legal Council of 9 deliberation system.
--
-- Usage:
--     psql -U miner_bot -d fortress_db -f division_legal/command_center/deliberation_events.sql
--
-- Idempotent: Safe to run multiple times.
-- Executed: 2026-03-02

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_cmd;

CREATE TABLE IF NOT EXISTS legal_cmd.deliberation_events (
    event_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_slug            VARCHAR(255) NOT NULL,
    case_number          VARCHAR(255),
    timestamp            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- Pillar 1: Context Freezing
    trigger_type         VARCHAR(50) NOT NULL,   -- MANUAL_RUN, RE_DELIBERATE, NEW_DOCUMENT_INGEST
    qdrant_vector_ids    TEXT[],                  -- Exact Qdrant point UUIDs retrieved as context
    context_chunks       TEXT[],                  -- Preserved text chunks (survives re-indexing)
    user_prompt          TEXT NOT NULL,

    -- Pillar 2: Hardware & Model Provenance
    moe_roster_snapshot  JSONB NOT NULL,          -- Frozen roster: seat, persona, provider, model version
    seat_opinions        JSONB NOT NULL,          -- 9 opinion objects: signal, conviction, model_used, elapsed_ms

    -- Pillar 3: Consensus Output
    counsel_results      JSONB NOT NULL,
    consensus_signal     VARCHAR(50),
    consensus_conviction NUMERIC(4,3),
    execution_time_ms    INTEGER,

    -- Pillar 4: Cryptographic Proof
    sha256_signature     VARCHAR(64) UNIQUE NOT NULL  -- SHA-256 of canonical payload
);

CREATE INDEX IF NOT EXISTS idx_delib_case ON legal_cmd.deliberation_events(case_slug, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_delib_sig  ON legal_cmd.deliberation_events(sha256_signature);

COMMENT ON TABLE legal_cmd.deliberation_events IS 'Immutable event-sourced ledger for Legal Council of 9 deliberations. Each row is SHA-256 signed at creation and never updated.';
COMMENT ON COLUMN legal_cmd.deliberation_events.qdrant_vector_ids IS 'Exact Qdrant point UUIDs retrieved as context for this deliberation (Context Freezing).';
COMMENT ON COLUMN legal_cmd.deliberation_events.context_chunks IS 'Preserved text chunks from vector retrieval — survives re-indexing.';
COMMENT ON COLUMN legal_cmd.deliberation_events.moe_roster_snapshot IS 'Frozen MoE roster: seat, persona, provider, exact model version string.';
COMMENT ON COLUMN legal_cmd.deliberation_events.seat_opinions IS 'Array of 9 opinion objects with signal, conviction, reasoning, model_used, elapsed_ms.';
COMMENT ON COLUMN legal_cmd.deliberation_events.sha256_signature IS 'SHA-256 hash of canonical payload (case + vectors + prompt + roster + results). Tamper-proof seal.';

COMMIT;
