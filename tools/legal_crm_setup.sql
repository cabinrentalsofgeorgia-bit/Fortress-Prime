-- FORTRESS PRIME — Legal CRM Schema Migration
-- ================================================
-- Creates correspondence tracking and deadline management tables
-- for the autonomous Legal CRM engine.
--
-- Usage:
--     psql -U admin -d fortress_db -f tools/legal_crm_setup.sql
--
-- Idempotent: Safe to run multiple times.

BEGIN;

-- ─── legal.correspondence ────────────────────────────────────────────────────
-- Tracks all outbound/inbound communications per case — the CRM's memory.

CREATE TABLE IF NOT EXISTS legal.correspondence (
    id              SERIAL PRIMARY KEY,
    case_id         INTEGER REFERENCES legal.cases(id),
    direction       TEXT NOT NULL DEFAULT 'outbound',   -- outbound, inbound, internal
    comm_type       TEXT NOT NULL,                       -- email, certified_mail, court_filing, phone_note
    recipient       TEXT,                                -- who it's addressed to
    recipient_email TEXT,
    subject         TEXT NOT NULL,
    body            TEXT,                                -- full text of the communication
    status          TEXT DEFAULT 'draft',                -- draft, approved, sent, delivered, filed
    gmail_draft_id  TEXT,                                -- Gmail draft ID if created via API
    tracking_number TEXT,                                -- USPS tracking, court filing number
    file_path       TEXT,                                -- NAS path to saved document
    approved_by     TEXT,                                -- who approved it for sending
    approved_at     TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_correspondence_case ON legal.correspondence(case_id);
CREATE INDEX IF NOT EXISTS idx_correspondence_status ON legal.correspondence(status);

-- ─── legal.deadlines ─────────────────────────────────────────────────────────
-- Dedicated deadline tracking with automatic escalation triggers.

CREATE TABLE IF NOT EXISTS legal.deadlines (
    id                  SERIAL PRIMARY KEY,
    case_id             INTEGER REFERENCES legal.cases(id),
    deadline_type       TEXT NOT NULL,           -- answer_due, discovery, motion, hearing, statute_of_limitations
    description         TEXT NOT NULL,
    due_date            DATE NOT NULL,
    alert_days_before   INTEGER DEFAULT 7,
    status              TEXT DEFAULT 'pending',  -- pending, extended, completed, missed
    extended_to         DATE,
    extension_reason    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deadlines_case ON legal.deadlines(case_id);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON legal.deadlines(due_date);
CREATE INDEX IF NOT EXISTS idx_deadlines_status ON legal.deadlines(status);

COMMIT;
