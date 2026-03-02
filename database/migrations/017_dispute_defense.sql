-- Migration 017: Dispute Defense — Chargeback Ironclad evidence tracking
-- Effective: 2026-03-01
-- Purpose: Track Stripe dispute lifecycle, evidence compilation, and submission outcomes.

BEGIN;

CREATE TABLE IF NOT EXISTS dispute_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id      TEXT NOT NULL UNIQUE,           -- Stripe dispute ID (dp_xxx)
    payment_intent  TEXT,                            -- Stripe payment_intent ID (pi_xxx)
    reservation_id  UUID REFERENCES reservations(id) ON DELETE SET NULL,
    guest_id        UUID REFERENCES guests(id) ON DELETE SET NULL,
    property_id     UUID REFERENCES properties(id) ON DELETE SET NULL,

    -- Evidence artifacts
    rental_agreement_id  UUID REFERENCES rental_agreements(id) ON DELETE SET NULL,
    evidence_pdf_path    TEXT,                       -- Local/NAS path to compiled evidence packet
    iot_events_count     INTEGER DEFAULT 0,          -- Number of IoT lock events included

    -- Stripe dispute metadata
    dispute_amount       NUMERIC(12,2),              -- Disputed amount in cents (Stripe)
    dispute_reason       TEXT,                        -- Stripe reason code
    dispute_status       TEXT DEFAULT 'needs_response',  -- needs_response, under_review, won, lost, warning_needs_response

    -- Submission tracking
    submitted_to_stripe_at  TIMESTAMP WITH TIME ZONE,
    stripe_response         JSONB,                   -- Raw Stripe API response on evidence submission
    status                  TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'evidence_compiled', 'submitted', 'won', 'lost', 'expired')),

    -- Audit
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispute_evidence_reservation ON dispute_evidence(reservation_id);
CREATE INDEX IF NOT EXISTS idx_dispute_evidence_status ON dispute_evidence(status);
CREATE INDEX IF NOT EXISTS idx_dispute_evidence_dispute_id ON dispute_evidence(dispute_id);

COMMENT ON TABLE dispute_evidence IS 'Chargeback Ironclad — tracks Stripe dispute lifecycle and evidence submissions';

COMMIT;
