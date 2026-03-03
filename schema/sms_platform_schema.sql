-- ============================================================================
-- FORTRESS SMS PLATFORM - Database Schema
-- Sovereign SMS Infrastructure with AI Training Pipeline
-- ============================================================================

-- Drop existing tables if recreating
-- DROP TABLE IF EXISTS message_archive CASCADE;
-- DROP TABLE IF EXISTS conversation_threads CASCADE;
-- DROP TABLE IF EXISTS guest_profiles CASCADE;
-- DROP TABLE IF EXISTS sms_providers CASCADE;
-- DROP TABLE IF EXISTS property_sms_config CASCADE;
-- DROP TABLE IF EXISTS ai_training_labels CASCADE;
-- DROP TABLE IF EXISTS message_analytics CASCADE;

-- ============================================================================
-- MESSAGE ARCHIVE - All historical and real-time messages
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_archive (
    id BIGSERIAL PRIMARY KEY,
    
    -- Source tracking
    source VARCHAR(50) NOT NULL,              -- 'ruebarue', 'twilio', 'bandwidth', 'sovereign'
    external_id VARCHAR(255),                 -- Provider's message ID
    provider_account VARCHAR(100),            -- Which provider account
    
    -- Message details
    phone_number VARCHAR(20) NOT NULL,
    guest_name VARCHAR(255),
    message_body TEXT NOT NULL,
    direction VARCHAR(10) NOT NULL,           -- 'inbound', 'outbound'
    media_url TEXT[],                         -- MMS attachments
    
    -- Timestamps
    sent_at TIMESTAMP,
    received_at TIMESTAMP,
    delivered_at TIMESTAMP,
    read_at TIMESTAMP,
    failed_at TIMESTAMP,
    
    -- Context
    property_id INTEGER,
    cabin_name VARCHAR(100),
    reservation_id VARCHAR(100),
    reservation_checkin DATE,
    reservation_checkout DATE,
    
    -- Classification (for AI)
    intent VARCHAR(50),                       -- 'checkin', 'wifi', 'directions', 'maintenance', etc.
    intent_confidence DECIMAL(4,3),           -- 0.000 to 1.000
    sub_intent VARCHAR(50),                   -- More specific classification
    sentiment VARCHAR(20),                    -- 'positive', 'neutral', 'negative', 'urgent'
    urgency_level INTEGER,                    -- 1-5 scale
    contains_question BOOLEAN DEFAULT FALSE,
    requires_human BOOLEAN DEFAULT FALSE,
    
    -- Response tracking
    response_generated_by VARCHAR(50),        -- 'ai', 'human', 'template'
    response_time_seconds INTEGER,
    ai_model_used VARCHAR(100),               -- 'qwen2.5:7b', 'deepseek-r1:70b', etc.
    response_quality_score INTEGER,           -- 1-5 rating (human feedback)
    resolution_status VARCHAR(20),            -- 'resolved', 'pending', 'escalated'
    
    -- AI training metadata
    used_for_training BOOLEAN DEFAULT FALSE,
    training_label VARCHAR(50),
    training_split VARCHAR(10),               -- 'train', 'val', 'test'
    human_reviewed BOOLEAN DEFAULT FALSE,
    human_reviewer VARCHAR(100),
    review_notes TEXT,
    approved_for_fine_tuning BOOLEAN DEFAULT FALSE,
    
    -- Delivery status
    status VARCHAR(50),                       -- 'queued', 'sent', 'delivered', 'failed', 'undelivered'
    error_code VARCHAR(50),
    error_message TEXT,
    num_segments INTEGER DEFAULT 1,
    
    -- Cost tracking
    cost_usd DECIMAL(10,6),
    provider_cost_usd DECIMAL(10,6),
    
    -- Audit
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    extracted_at TIMESTAMP,
    extraction_method VARCHAR(50),
    
    -- Constraints
    CONSTRAINT valid_direction CHECK (direction IN ('inbound', 'outbound')),
    CONSTRAINT valid_sentiment CHECK (sentiment IN ('positive', 'neutral', 'negative', 'urgent') OR sentiment IS NULL),
    CONSTRAINT valid_urgency CHECK (urgency_level BETWEEN 1 AND 5 OR urgency_level IS NULL),
    CONSTRAINT valid_quality CHECK (response_quality_score BETWEEN 1 AND 5 OR response_quality_score IS NULL)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_message_phone ON message_archive(phone_number);
CREATE INDEX IF NOT EXISTS idx_message_sent_at ON message_archive(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_property ON message_archive(property_id);
CREATE INDEX IF NOT EXISTS idx_message_intent ON message_archive(intent);
CREATE INDEX IF NOT EXISTS idx_message_training ON message_archive(used_for_training) WHERE used_for_training = TRUE;
CREATE INDEX IF NOT EXISTS idx_message_direction ON message_archive(direction);
CREATE INDEX IF NOT EXISTS idx_message_status ON message_archive(status);
CREATE INDEX IF NOT EXISTS idx_message_external_id ON message_archive(external_id);
CREATE INDEX IF NOT EXISTS idx_message_source ON message_archive(source);

-- Full text search
CREATE INDEX IF NOT EXISTS idx_message_body_fts ON message_archive USING gin(to_tsvector('english', message_body));

-- ============================================================================
-- CONVERSATION THREADS - Grouped message sequences
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversation_threads (
    id BIGSERIAL PRIMARY KEY,
    
    -- Thread identification
    phone_number VARCHAR(20) NOT NULL,
    property_id INTEGER,
    thread_hash VARCHAR(64) UNIQUE,           -- MD5(phone + property + date_bucket)
    
    -- Thread metrics
    started_at TIMESTAMP NOT NULL,
    last_message_at TIMESTAMP NOT NULL,
    message_count INTEGER DEFAULT 0,
    inbound_count INTEGER DEFAULT 0,
    outbound_count INTEGER DEFAULT 0,
    
    -- Thread classification
    primary_intent VARCHAR(50),
    status VARCHAR(20),                       -- 'active', 'resolved', 'escalated', 'abandoned'
    resolution_time_seconds INTEGER,
    
    -- AI performance
    handled_by_ai BOOLEAN DEFAULT FALSE,
    ai_success BOOLEAN,
    escalated_to_human BOOLEAN DEFAULT FALSE,
    escalation_reason TEXT,
    
    -- Guest satisfaction
    guest_satisfaction_score INTEGER,         -- 1-5 from post-conversation survey
    guest_feedback TEXT,
    
    -- Metadata
    reservation_id VARCHAR(100),
    cabin_name VARCHAR(100),
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT valid_status CHECK (status IN ('active', 'resolved', 'escalated', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_thread_phone ON conversation_threads(phone_number);
CREATE INDEX IF NOT EXISTS idx_thread_property ON conversation_threads(property_id);
CREATE INDEX IF NOT EXISTS idx_thread_status ON conversation_threads(status);
CREATE INDEX IF NOT EXISTS idx_thread_last_message ON conversation_threads(last_message_at DESC);

-- ============================================================================
-- GUEST PROFILES - Enriched guest data over time
-- ============================================================================
CREATE TABLE IF NOT EXISTS guest_profiles (
    id BIGSERIAL PRIMARY KEY,
    
    -- Identity
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    alternate_phones VARCHAR(20)[],
    
    -- Behavior patterns
    total_messages INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    avg_response_time_seconds INTEGER,
    preferred_contact_time VARCHAR(20),       -- 'morning', 'afternoon', 'evening', 'night'
    typical_response_length VARCHAR(20),      -- 'brief', 'moderate', 'detailed'
    
    -- Common questions (array of intents)
    common_intents TEXT[],
    frequently_asked_questions TEXT[],
    
    -- Sentiment analysis
    overall_sentiment VARCHAR(20),
    sentiment_trend VARCHAR(20),              -- 'improving', 'stable', 'declining'
    positive_interaction_ratio DECIMAL(3,2),  -- 0.00 to 1.00
    avg_satisfaction_score DECIMAL(3,2),
    
    -- Booking history
    total_stays INTEGER DEFAULT 0,
    favorite_cabins TEXT[],
    lifetime_value DECIMAL(10,2),
    last_stay_date DATE,
    next_booking_date DATE,
    
    -- AI personalization
    communication_style VARCHAR(50),          -- 'formal', 'casual', 'brief', 'friendly'
    language_preference VARCHAR(10) DEFAULT 'en',
    accessibility_needs TEXT[],
    special_requests TEXT[],
    
    -- Flags
    vip_guest BOOLEAN DEFAULT FALSE,
    requires_human_touch BOOLEAN DEFAULT FALSE,
    do_not_contact BOOLEAN DEFAULT FALSE,
    opted_out_at TIMESTAMP,
    
    -- Contact history
    first_contact TIMESTAMP,
    last_contact TIMESTAMP,
    days_since_last_contact INTEGER,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT valid_overall_sentiment CHECK (overall_sentiment IN ('positive', 'neutral', 'negative') OR overall_sentiment IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_guest_phone ON guest_profiles(phone_number);
CREATE INDEX IF NOT EXISTS idx_guest_email ON guest_profiles(email);
CREATE INDEX IF NOT EXISTS idx_guest_vip ON guest_profiles(vip_guest) WHERE vip_guest = TRUE;
CREATE INDEX IF NOT EXISTS idx_guest_last_contact ON guest_profiles(last_contact DESC);

-- ============================================================================
-- SMS PROVIDERS - Multi-provider configuration
-- ============================================================================
CREATE TABLE IF NOT EXISTS sms_providers (
    id SERIAL PRIMARY KEY,
    
    -- Provider details
    name VARCHAR(50) NOT NULL,                -- 'twilio', 'bandwidth', 'plivo', 'sovereign'
    account_sid VARCHAR(255),
    auth_token_encrypted TEXT,                -- Encrypted auth token
    
    -- Phone numbers
    phone_numbers TEXT[],
    
    -- Capabilities
    supports_mms BOOLEAN DEFAULT FALSE,
    supports_unicode BOOLEAN DEFAULT TRUE,
    max_message_length INTEGER DEFAULT 160,
    
    -- Routing priority
    priority INTEGER DEFAULT 100,             -- Lower = higher priority
    enabled BOOLEAN DEFAULT TRUE,
    
    -- Cost
    cost_per_message DECIMAL(6,4),
    cost_per_segment DECIMAL(6,4),
    monthly_fee DECIMAL(8,2),
    
    -- Performance tracking
    total_messages_sent INTEGER DEFAULT 0,
    success_rate DECIMAL(5,4),
    avg_delivery_time_seconds INTEGER,
    last_failure_at TIMESTAMP,
    consecutive_failures INTEGER DEFAULT 0,
    
    -- Rate limits
    rate_limit_per_second INTEGER,
    rate_limit_per_minute INTEGER,
    rate_limit_per_hour INTEGER,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(name, account_sid)
);

CREATE INDEX IF NOT EXISTS idx_provider_enabled ON sms_providers(enabled, priority) WHERE enabled = TRUE;

-- ============================================================================
-- PROPERTY SMS CONFIGURATION - Per-property settings
-- ============================================================================
CREATE TABLE IF NOT EXISTS property_sms_config (
    id SERIAL PRIMARY KEY,
    
    -- Property identification
    property_id INTEGER NOT NULL UNIQUE,
    property_name VARCHAR(255) NOT NULL,
    cabin_name VARCHAR(100),
    
    -- Phone assignment
    assigned_phone_number VARCHAR(20) NOT NULL,
    provider_id INTEGER REFERENCES sms_providers(id),
    
    -- AI settings
    ai_enabled BOOLEAN DEFAULT TRUE,
    ai_model_preference VARCHAR(100),         -- 'fast', 'balanced', 'accurate'
    auto_reply_enabled BOOLEAN DEFAULT TRUE,
    require_human_approval BOOLEAN DEFAULT FALSE,
    
    -- Business hours
    business_hours_start TIME,                -- e.g., '08:00:00'
    business_hours_end TIME,                  -- e.g., '20:00:00'
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    after_hours_behavior VARCHAR(50),         -- 'queue', 'auto_reply', 'forward'
    
    -- Templates
    welcome_message_template TEXT,
    checkin_info_template TEXT,
    checkout_reminder_template TEXT,
    wifi_info_template TEXT,
    
    -- Property context (for AI)
    wifi_ssid VARCHAR(100),
    wifi_password VARCHAR(100),
    door_code VARCHAR(20),
    address TEXT,
    checkin_instructions TEXT,
    house_rules TEXT,
    emergency_contact VARCHAR(20),
    
    -- Escalation
    escalation_phone VARCHAR(20),
    escalation_email VARCHAR(255),
    escalation_keywords TEXT[],               -- Words that trigger human escalation
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_property_phone ON property_sms_config(assigned_phone_number);
CREATE INDEX IF NOT EXISTS idx_property_ai_enabled ON property_sms_config(ai_enabled);

-- ============================================================================
-- AI TRAINING LABELS - Human-labeled data for training
-- ============================================================================
CREATE TABLE IF NOT EXISTS ai_training_labels (
    id BIGSERIAL PRIMARY KEY,
    
    message_id BIGINT REFERENCES message_archive(id),
    
    -- Labels
    labeled_intent VARCHAR(50) NOT NULL,
    labeled_sentiment VARCHAR(20),
    labeled_urgency INTEGER,
    requires_human BOOLEAN,
    
    -- Quality scoring
    response_appropriateness INTEGER,         -- 1-5 scale
    response_accuracy INTEGER,                -- 1-5 scale
    response_tone INTEGER,                    -- 1-5 scale
    
    -- Labeler info
    labeled_by VARCHAR(100) NOT NULL,
    labeled_at TIMESTAMP DEFAULT NOW(),
    labeling_confidence INTEGER,              -- 1-5 scale
    notes TEXT,
    
    -- Training use
    used_in_training_run VARCHAR(100),
    training_epoch INTEGER,
    
    CONSTRAINT valid_appropriateness CHECK (response_appropriateness BETWEEN 1 AND 5 OR response_appropriateness IS NULL),
    CONSTRAINT valid_accuracy CHECK (response_accuracy BETWEEN 1 AND 5 OR response_accuracy IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_training_message ON ai_training_labels(message_id);
CREATE INDEX IF NOT EXISTS idx_training_intent ON ai_training_labels(labeled_intent);
CREATE INDEX IF NOT EXISTS idx_training_labeled_at ON ai_training_labels(labeled_at DESC);

-- ============================================================================
-- MESSAGE ANALYTICS - Aggregated stats for dashboards
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_analytics (
    id BIGSERIAL PRIMARY KEY,
    
    -- Time bucket
    date DATE NOT NULL,
    hour INTEGER,                             -- 0-23, NULL for daily aggregates
    
    -- Dimensions
    property_id INTEGER,
    source VARCHAR(50),
    
    -- Volume metrics
    total_messages INTEGER DEFAULT 0,
    inbound_messages INTEGER DEFAULT 0,
    outbound_messages INTEGER DEFAULT 0,
    
    -- AI metrics
    ai_handled_count INTEGER DEFAULT 0,
    human_handled_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    ai_success_rate DECIMAL(5,4),
    
    -- Performance metrics
    avg_response_time_seconds INTEGER,
    median_response_time_seconds INTEGER,
    p95_response_time_seconds INTEGER,
    
    -- Intent distribution
    intent_distribution JSONB,               -- {"checkin": 45, "wifi": 30, ...}
    
    -- Sentiment
    positive_messages INTEGER DEFAULT 0,
    neutral_messages INTEGER DEFAULT 0,
    negative_messages INTEGER DEFAULT 0,
    urgent_messages INTEGER DEFAULT 0,
    
    -- Cost
    total_cost_usd DECIMAL(10,2),
    cost_per_message DECIMAL(6,4),
    
    -- Quality
    avg_satisfaction_score DECIMAL(3,2),
    
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(date, hour, property_id, source)
);

CREATE INDEX IF NOT EXISTS idx_analytics_date ON message_analytics(date DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_property ON message_analytics(property_id);

-- ============================================================================
-- VIEWS - Useful queries
-- ============================================================================

-- Recent conversations with context
CREATE OR REPLACE VIEW recent_conversations AS
SELECT 
    ct.id as thread_id,
    ct.phone_number,
    gp.name as guest_name,
    ct.property_id,
    psc.cabin_name,
    ct.message_count,
    ct.status,
    ct.last_message_at,
    ct.handled_by_ai,
    gp.vip_guest,
    (SELECT message_body FROM message_archive 
     WHERE phone_number = ct.phone_number 
     ORDER BY sent_at DESC LIMIT 1) as last_message
FROM conversation_threads ct
LEFT JOIN guest_profiles gp ON ct.phone_number = gp.phone_number
LEFT JOIN property_sms_config psc ON ct.property_id = psc.property_id
WHERE ct.status = 'active'
ORDER BY ct.last_message_at DESC;

-- AI training dataset
CREATE OR REPLACE VIEW ai_training_dataset AS
SELECT 
    ma.id,
    ma.message_body as input_text,
    ma.intent as intent_label,
    ma.sentiment as sentiment_label,
    ma.direction,
    atl.labeled_intent,
    atl.labeled_sentiment,
    atl.response_appropriateness,
    ma.phone_number,
    ma.property_id,
    ma.sent_at
FROM message_archive ma
LEFT JOIN ai_training_labels atl ON ma.id = atl.message_id
WHERE ma.used_for_training = TRUE
AND ma.human_reviewed = TRUE;

-- Daily performance metrics
CREATE OR REPLACE VIEW daily_performance AS
SELECT 
    date,
    SUM(total_messages) as total_messages,
    SUM(inbound_messages) as inbound_messages,
    SUM(outbound_messages) as outbound_messages,
    AVG(ai_success_rate) as avg_ai_success_rate,
    AVG(avg_response_time_seconds) as avg_response_time,
    SUM(total_cost_usd) as total_cost,
    AVG(avg_satisfaction_score) as avg_satisfaction
FROM message_analytics
WHERE hour IS NULL
GROUP BY date
ORDER BY date DESC;

-- ============================================================================
-- TRIGGERS - Auto-update timestamps
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_message_archive_updated_at BEFORE UPDATE ON message_archive
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversation_threads_updated_at BEFORE UPDATE ON conversation_threads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_guest_profiles_updated_at BEFORE UPDATE ON guest_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- GRANTS - Security
-- ============================================================================

-- Grant read/write to application user
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO miner_bot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO miner_bot;

-- ============================================================================
-- SAMPLE DATA - For testing (optional)
-- ============================================================================

-- Insert sample provider
INSERT INTO sms_providers (name, priority, cost_per_message, enabled) 
VALUES ('twilio', 1, 0.0079, TRUE)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE message_archive IS 'Complete archive of all SMS messages from all sources';
COMMENT ON TABLE conversation_threads IS 'Grouped message sequences for analytics and AI training';
COMMENT ON TABLE guest_profiles IS 'Enriched guest profiles built from interaction history';
COMMENT ON TABLE sms_providers IS 'Multi-provider SMS gateway configuration';
COMMENT ON TABLE property_sms_config IS 'Per-property SMS settings and AI configuration';
COMMENT ON TABLE ai_training_labels IS 'Human-labeled training data for model fine-tuning';
COMMENT ON TABLE message_analytics IS 'Pre-aggregated analytics for dashboard performance';
