-- =====================================================================
-- FORTRESS PRIME — Guest Agent Schema
-- AI-powered guest communication agent tables
-- =====================================================================

-- Response queue: Every AI-generated draft goes here for review
CREATE TABLE IF NOT EXISTS agent_response_queue (
    id              BIGSERIAL PRIMARY KEY,
    
    -- Inbound message reference
    inbound_message_id  BIGINT REFERENCES message_archive(id),
    phone_number        VARCHAR(20) NOT NULL,
    guest_name          VARCHAR(255),
    cabin_name          VARCHAR(100),
    reservation_id      VARCHAR(100),
    
    -- Inbound content
    guest_message       TEXT NOT NULL,
    
    -- AI classification
    intent              VARCHAR(50),
    intent_confidence   DECIMAL(4,3),
    sentiment           VARCHAR(20),
    urgency_level       INTEGER DEFAULT 1,
    escalation_required BOOLEAN DEFAULT FALSE,
    escalation_reason   TEXT,
    
    -- AI draft
    ai_draft            TEXT NOT NULL,
    ai_model            VARCHAR(100),
    ai_duration_ms      INTEGER,
    knowledge_sources   JSONB,              -- which KB articles, templates, history used
    confidence_score    DECIMAL(4,3),       -- how confident the agent is in this response
    
    -- Review workflow
    status              VARCHAR(20) NOT NULL DEFAULT 'pending_review',
        -- pending_review, approved, edited, rejected, sent, expired
    reviewed_by         VARCHAR(100),
    reviewed_at         TIMESTAMP,
    edited_draft        TEXT,               -- Taylor's edited version (if modified)
    review_notes        TEXT,
    
    -- Delivery
    sent_at             TIMESTAMP,
    sent_via            VARCHAR(20),        -- 'sms', 'email', 'both'
    outbound_message_id BIGINT,             -- reference to message_archive
    delivery_status     VARCHAR(20),
    
    -- Timestamps
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),
    expires_at          TIMESTAMP           -- auto-expire stale drafts
);

-- Indexes for the review dashboard
CREATE INDEX IF NOT EXISTS idx_arq_status ON agent_response_queue(status);
CREATE INDEX IF NOT EXISTS idx_arq_created ON agent_response_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_arq_cabin ON agent_response_queue(cabin_name);
CREATE INDEX IF NOT EXISTS idx_arq_urgency ON agent_response_queue(urgency_level DESC);

-- Agent performance tracking
CREATE TABLE IF NOT EXISTS agent_performance_log (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL DEFAULT CURRENT_DATE,
    
    -- Volume
    messages_received   INTEGER DEFAULT 0,
    drafts_generated    INTEGER DEFAULT 0,
    drafts_approved     INTEGER DEFAULT 0,  -- approved as-is
    drafts_edited       INTEGER DEFAULT 0,  -- approved with edits
    drafts_rejected     INTEGER DEFAULT 0,  -- rejected by human
    auto_sent           INTEGER DEFAULT 0,  -- sent without review (future)
    
    -- Quality
    avg_confidence      DECIMAL(4,3),
    avg_response_time_ms INTEGER,
    escalation_count    INTEGER DEFAULT 0,
    
    -- By intent
    intent_breakdown    JSONB,              -- {"CHECKIN": 5, "WIFI": 3, ...}
    
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_apl_date ON agent_performance_log(date);

-- View: Pending review items for the dashboard
CREATE OR REPLACE VIEW pending_reviews AS
SELECT 
    arq.id,
    arq.phone_number,
    arq.guest_name,
    arq.cabin_name,
    arq.guest_message,
    arq.intent,
    arq.sentiment,
    arq.urgency_level,
    arq.escalation_required,
    arq.ai_draft,
    arq.confidence_score,
    arq.ai_model,
    arq.created_at,
    arq.expires_at,
    gp.communication_style,
    gp.total_stays,
    gp.vip_guest,
    gp.overall_sentiment as guest_overall_sentiment
FROM agent_response_queue arq
LEFT JOIN guest_profiles gp ON arq.phone_number = gp.phone_number
WHERE arq.status = 'pending_review'
ORDER BY arq.urgency_level DESC, arq.created_at ASC;
