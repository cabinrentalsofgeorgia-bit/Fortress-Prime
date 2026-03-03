-- FORTRESS PRIME — Legal Command Center Schema
-- ==============================================
-- Tracks attorneys, meetings, matters, timeline entries, and documents
-- for building an ongoing legal record across all subjects.
--
-- Usage:
--     psql -U admin -d fortress_db -f division_legal/command_center/schema.sql
--
-- Idempotent: Safe to run multiple times.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_cmd;

-- ─── Attorneys ─────────────────────────────────────────────────────────────
-- Every attorney or law firm you've engaged.

CREATE TABLE IF NOT EXISTS legal_cmd.attorneys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    firm_name       TEXT,
    specialty       TEXT,                      -- litigation, tax, real_estate, corporate, employment, IP, general
    email           TEXT,
    phone           TEXT,
    address         TEXT,
    website         TEXT,
    bar_number      TEXT,
    bar_state       TEXT,
    hourly_rate     NUMERIC(10,2),
    retainer_amount NUMERIC(10,2),
    retainer_status TEXT DEFAULT 'none',       -- none, active, expired, pending
    engagement_date DATE,
    status          TEXT DEFAULT 'active',     -- active, inactive, terminated
    rating          INTEGER CHECK (rating BETWEEN 1 AND 5),
    notes           TEXT,
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attorneys_status ON legal_cmd.attorneys(status);
CREATE INDEX IF NOT EXISTS idx_attorneys_specialty ON legal_cmd.attorneys(specialty);

-- ─── Matters ───────────────────────────────────────────────────────────────
-- Legal subjects or topics being tracked (cases, disputes, projects, reviews).

CREATE TABLE IF NOT EXISTS legal_cmd.matters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    reference_code  TEXT UNIQUE,               -- BHL-ERC-2023-001 style
    category        TEXT NOT NULL,              -- litigation, contract, tax, property, employment, corporate, compliance, estate, IP
    status          TEXT DEFAULT 'open',        -- open, active, monitoring, on_hold, resolved, closed
    priority        TEXT DEFAULT 'normal',      -- low, normal, high, critical
    description     TEXT,
    attorney_id     UUID REFERENCES legal_cmd.attorneys(id),
    opposing_party  TEXT,
    opposing_counsel TEXT,
    amount_at_stake NUMERIC(12,2),
    outcome         TEXT,
    outcome_date    DATE,
    next_action     TEXT,
    next_action_date DATE,
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_matters_status ON legal_cmd.matters(status);
CREATE INDEX IF NOT EXISTS idx_matters_category ON legal_cmd.matters(category);
CREATE INDEX IF NOT EXISTS idx_matters_attorney ON legal_cmd.matters(attorney_id);
CREATE INDEX IF NOT EXISTS idx_matters_priority ON legal_cmd.matters(priority);

-- ─── Meetings ──────────────────────────────────────────────────────────────
-- Every meeting, call, or consultation — who, when, where, what was discussed.

CREATE TABLE IF NOT EXISTS legal_cmd.meetings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id       UUID REFERENCES legal_cmd.matters(id),
    attorney_id     UUID REFERENCES legal_cmd.attorneys(id),
    title           TEXT NOT NULL,
    meeting_type    TEXT DEFAULT 'in_person',  -- in_person, phone, video, email_exchange, court_appearance
    meeting_date    TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER,
    location        TEXT,
    attendees       TEXT,                      -- comma-separated or free text
    summary         TEXT,                      -- what was discussed
    action_items    TEXT,                      -- follow-ups, next steps
    key_decisions   TEXT,                      -- decisions made
    documents_discussed TEXT,                  -- referenced docs
    billable        BOOLEAN DEFAULT FALSE,
    cost            NUMERIC(10,2),
    follow_up_date  DATE,
    follow_up_notes TEXT,
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meetings_matter ON legal_cmd.meetings(matter_id);
CREATE INDEX IF NOT EXISTS idx_meetings_attorney ON legal_cmd.meetings(attorney_id);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON legal_cmd.meetings(meeting_date);

-- ─── Timeline ──────────────────────────────────────────────────────────────
-- Running record of events, actions, and notes on any matter.

CREATE TABLE IF NOT EXISTS legal_cmd.timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id       UUID NOT NULL REFERENCES legal_cmd.matters(id),
    entry_type      TEXT NOT NULL,             -- note, action, decision, filing, correspondence, research, payment, milestone
    title           TEXT NOT NULL,
    body            TEXT,
    entered_by      TEXT DEFAULT 'owner',
    importance      TEXT DEFAULT 'normal',     -- low, normal, high, critical
    related_meeting_id UUID REFERENCES legal_cmd.meetings(id),
    related_attorney_id UUID REFERENCES legal_cmd.attorneys(id),
    document_ref    TEXT,                      -- NAS path or URL
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_matter ON legal_cmd.timeline(matter_id);
CREATE INDEX IF NOT EXISTS idx_timeline_type ON legal_cmd.timeline(entry_type);
CREATE INDEX IF NOT EXISTS idx_timeline_created ON legal_cmd.timeline(created_at);

-- ─── Documents ─────────────────────────────────────────────────────────────
-- Document references linked to matters.

CREATE TABLE IF NOT EXISTS legal_cmd.documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id       UUID REFERENCES legal_cmd.matters(id),
    title           TEXT NOT NULL,
    doc_type        TEXT,                      -- contract, brief, correspondence, evidence, filing, invoice, memo
    file_path       TEXT,                      -- NAS or local path
    file_url        TEXT,
    description     TEXT,
    uploaded_by     TEXT DEFAULT 'owner',
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_matter ON legal_cmd.documents(matter_id);
CREATE INDEX IF NOT EXISTS idx_documents_type ON legal_cmd.documents(doc_type);

-- ─── Auto-update timestamps ────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION legal_cmd.update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_attorneys_updated BEFORE UPDATE ON legal_cmd.attorneys
        FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_matters_updated BEFORE UPDATE ON legal_cmd.matters
        FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_meetings_updated BEFORE UPDATE ON legal_cmd.meetings
        FOR EACH ROW EXECUTE FUNCTION legal_cmd.update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── Deliberation Events (Verifiable Intelligence Engine) ─────────────────
-- Immutable event-sourced ledger for Legal Council of 9 deliberations.
-- Each row is SHA-256 signed at creation and never updated.

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

COMMIT;
