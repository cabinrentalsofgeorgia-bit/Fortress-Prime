-- ============================================================================
-- Fortress Guest Platform (FGP) - Database Schema
-- PostgreSQL 15+
-- Purpose: Complete guest communication & lifecycle management system
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- For fuzzy text search

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Properties (Cabins)
CREATE TABLE IF NOT EXISTS properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    slug VARCHAR(255) NOT NULL UNIQUE,
    property_type VARCHAR(50) NOT NULL, -- cabin, cottage, house
    bedrooms INTEGER NOT NULL,
    bathrooms DECIMAL(3,1) NOT NULL,
    max_guests INTEGER NOT NULL,
    address TEXT,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    
    -- Access & Connectivity
    wifi_ssid VARCHAR(255),
    wifi_password VARCHAR(255),
    access_code_type VARCHAR(50), -- keypad, lockbox, smart_lock
    access_code_location TEXT,
    parking_instructions TEXT,
    
    -- Metadata
    streamline_property_id VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_properties_slug ON properties(slug);
CREATE INDEX idx_properties_streamline_id ON properties(streamline_property_id);

-- Guests
CREATE TABLE IF NOT EXISTS guests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone_number VARCHAR(20) NOT NULL UNIQUE, -- E.164 format
    email VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    
    -- Communication Preferences
    language_preference VARCHAR(10) DEFAULT 'en',
    opt_in_marketing BOOLEAN DEFAULT true,
    preferred_contact_method VARCHAR(20) DEFAULT 'sms', -- sms, email, both
    
    -- Analytics
    total_stays INTEGER DEFAULT 0,
    total_messages_sent INTEGER DEFAULT 0,
    total_messages_received INTEGER DEFAULT 0,
    average_rating DECIMAL(3,2),
    last_stay_date DATE,
    
    -- Metadata
    streamline_guest_id VARCHAR(100),
    notes TEXT,
    tags TEXT[], -- ['vip', 'repeat', 'problem']
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_guests_phone ON guests(phone_number);
CREATE INDEX idx_guests_email ON guests(email);
CREATE INDEX idx_guests_last_stay ON guests(last_stay_date DESC);

-- Reservations
CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    confirmation_code VARCHAR(50) NOT NULL UNIQUE,
    
    -- Relations
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    
    -- Dates & Guests
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    num_guests INTEGER NOT NULL,
    num_adults INTEGER,
    num_children INTEGER,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'confirmed', 
    -- confirmed, checked_in, checked_out, cancelled, no_show
    
    -- Access
    access_code VARCHAR(20),
    access_code_valid_from TIMESTAMP,
    access_code_valid_until TIMESTAMP,
    
    -- Booking Details
    booking_source VARCHAR(100), -- airbnb, vrbo, direct, etc
    total_amount DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Communication
    digital_guide_sent BOOLEAN DEFAULT false,
    pre_arrival_sent BOOLEAN DEFAULT false,
    access_info_sent BOOLEAN DEFAULT false,
    mid_stay_checkin_sent BOOLEAN DEFAULT false,
    checkout_reminder_sent BOOLEAN DEFAULT false,
    post_stay_followup_sent BOOLEAN DEFAULT false,
    
    -- Ratings & Feedback
    guest_rating INTEGER, -- 1-5
    guest_feedback TEXT,
    internal_notes TEXT,
    
    -- Metadata
    streamline_reservation_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reservations_guest_id ON reservations(guest_id);
CREATE INDEX idx_reservations_property_id ON reservations(property_id);
CREATE INDEX idx_reservations_check_in ON reservations(check_in_date);
CREATE INDEX idx_reservations_check_out ON reservations(check_out_date);
CREATE INDEX idx_reservations_status ON reservations(status);
CREATE INDEX idx_reservations_confirmation ON reservations(confirmation_code);

-- Messages (SMS Communication)
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id VARCHAR(255), -- Twilio MessageSid
    
    -- Relations
    guest_id UUID REFERENCES guests(id) ON DELETE SET NULL,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    
    -- Message Details
    direction VARCHAR(20) NOT NULL, -- inbound, outbound
    phone_from VARCHAR(20) NOT NULL,
    phone_to VARCHAR(20) NOT NULL,
    body TEXT NOT NULL,
    
    -- Classification (AI-powered)
    intent VARCHAR(50), -- wifi_question, access_code, maintenance, etc
    sentiment VARCHAR(20), -- positive, neutral, negative, urgent
    category VARCHAR(50), -- info_request, complaint, booking, emergency
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'sent',
    -- queued, sent, delivered, failed, received
    
    -- AI Response
    is_auto_response BOOLEAN DEFAULT false,
    ai_confidence DECIMAL(4,3), -- 0.0-1.0
    requires_human_review BOOLEAN DEFAULT false,
    human_reviewed_at TIMESTAMP,
    human_reviewed_by VARCHAR(100),
    
    -- Delivery
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    read_at TIMESTAMP,
    error_code VARCHAR(50),
    error_message TEXT,
    
    -- Metadata
    provider VARCHAR(50) DEFAULT 'twilio',
    cost_amount DECIMAL(8,4),
    num_segments INTEGER DEFAULT 1,
    trace_id UUID,
    metadata JSONB, -- Provider-specific data
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_guest_id ON messages(guest_id);
CREATE INDEX idx_messages_reservation_id ON messages(reservation_id);
CREATE INDEX idx_messages_direction ON messages(direction);
CREATE INDEX idx_messages_phone_from ON messages(phone_from);
CREATE INDEX idx_messages_created_at ON messages(created_at DESC);
CREATE INDEX idx_messages_intent ON messages(intent);
CREATE INDEX idx_messages_sentiment ON messages(sentiment);
CREATE INDEX idx_messages_external_id ON messages(external_id);

-- Message Templates
CREATE TABLE IF NOT EXISTS message_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL, -- pre_arrival, checkin, checkout, etc
    
    -- Template
    subject VARCHAR(255),
    body TEXT NOT NULL,
    variables TEXT[], -- ['first_name', 'property_name', 'check_in_date']
    
    -- Scheduling
    trigger_type VARCHAR(50), -- time_based, event_based, manual
    trigger_offset_days INTEGER, -- -7 = 7 days before check_in
    trigger_time TIME, -- 09:00:00 = 9am
    
    -- Settings
    is_active BOOLEAN DEFAULT true,
    send_priority INTEGER DEFAULT 0,
    language VARCHAR(10) DEFAULT 'en',
    
    -- Metadata
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_templates_category ON message_templates(category);
CREATE INDEX idx_templates_active ON message_templates(is_active);

-- Scheduled Messages
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Relations
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE CASCADE,
    template_id UUID REFERENCES message_templates(id) ON DELETE CASCADE,
    
    -- Schedule
    scheduled_for TIMESTAMP NOT NULL,
    sent_at TIMESTAMP,
    
    -- Content (rendered template)
    phone_to VARCHAR(20) NOT NULL,
    body TEXT NOT NULL,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- pending, sent, failed, cancelled
    
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    error_message TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scheduled_messages_guest_id ON scheduled_messages(guest_id);
CREATE INDEX idx_scheduled_messages_scheduled_for ON scheduled_messages(scheduled_for);
CREATE INDEX idx_scheduled_messages_status ON scheduled_messages(status);

-- Work Orders (Maintenance & Issues)
CREATE TABLE IF NOT EXISTS work_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_number VARCHAR(50) NOT NULL UNIQUE,
    
    -- Relations
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    guest_id UUID REFERENCES guests(id) ON DELETE SET NULL,
    reported_via_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    
    -- Issue Details
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(50) NOT NULL, 
    -- hvac, plumbing, electrical, hot_tub, appliance, other
    
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    -- low, medium, high, urgent
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    -- open, in_progress, waiting_parts, completed, cancelled
    
    -- Assignment
    assigned_to VARCHAR(255),
    assigned_at TIMESTAMP,
    
    -- Resolution
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    cost_amount DECIMAL(10,2),
    
    -- Photos
    photo_urls TEXT[],
    
    -- Metadata
    created_by VARCHAR(100), -- 'guest', 'staff', 'ai_detected'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_workorders_property_id ON work_orders(property_id);
CREATE INDEX idx_workorders_status ON work_orders(status);
CREATE INDEX idx_workorders_priority ON work_orders(priority);
CREATE INDEX idx_workorders_created_at ON work_orders(created_at DESC);

-- Digital Guestbook Content
CREATE TABLE IF NOT EXISTS guestbook_guides (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Relations
    property_id UUID REFERENCES properties(id) ON DELETE CASCADE,
    -- NULL property_id = area guide (shared across properties)
    
    -- Guide Details
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    guide_type VARCHAR(50) NOT NULL, -- home_guide, area_guide, emergency
    category VARCHAR(50), -- wifi, rules, amenities, restaurants, etc
    
    -- Content
    content TEXT NOT NULL, -- Markdown format
    icon VARCHAR(50), -- emoji or icon class
    
    -- Display
    display_order INTEGER DEFAULT 0,
    is_visible BOOLEAN DEFAULT true,
    visibility_rules JSONB, -- {'show_before_checkin': true, 'show_days': [-1, 0, 1]}
    
    -- Metadata
    view_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_guestbook_property_id ON guestbook_guides(property_id);
CREATE INDEX idx_guestbook_type ON guestbook_guides(guide_type);
CREATE INDEX idx_guestbook_visible ON guestbook_guides(is_visible);

-- Extras Marketplace (Upsells)
CREATE TABLE IF NOT EXISTS extras (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Product
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50), -- firewood, late_checkout, early_checkin, cleaning
    
    -- Pricing
    price DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Availability
    is_available BOOLEAN DEFAULT true,
    properties UUID[], -- Array of property IDs (NULL = all properties)
    
    -- Display
    image_url TEXT,
    display_order INTEGER DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_extras_available ON extras(is_available);

-- Extra Orders
CREATE TABLE IF NOT EXISTS extra_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Relations
    reservation_id UUID NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    extra_id UUID NOT NULL REFERENCES extras(id) ON DELETE CASCADE,
    
    -- Order Details
    quantity INTEGER DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- pending, confirmed, fulfilled, cancelled, refunded
    
    -- Fulfillment
    fulfilled_at TIMESTAMP,
    notes TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_extra_orders_reservation_id ON extra_orders(reservation_id);
CREATE INDEX idx_extra_orders_status ON extra_orders(status);

-- Analytics Events (for tracking)
CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Event
    event_type VARCHAR(100) NOT NULL,
    -- message_sent, message_received, ai_response, guide_viewed, etc
    
    -- Context
    guest_id UUID REFERENCES guests(id) ON DELETE SET NULL,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    
    -- Data
    event_data JSONB,
    
    -- Session
    session_id UUID,
    user_agent TEXT,
    ip_address INET,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_analytics_event_type ON analytics_events(event_type);
CREATE INDEX idx_analytics_created_at ON analytics_events(created_at DESC);
CREATE INDEX idx_analytics_guest_id ON analytics_events(guest_id);

-- Staff Users (for admin access)
CREATE TABLE IF NOT EXISTS staff_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Auth
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    
    -- Profile
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'staff',
    -- admin, manager, staff, maintenance
    
    -- Permissions
    permissions JSONB, -- {'can_send_messages': true, 'can_edit_properties': false}
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    last_login_at TIMESTAMP,
    
    -- Notifications
    notification_phone VARCHAR(20),
    notification_email VARCHAR(255),
    notify_urgent BOOLEAN DEFAULT true,
    notify_workorders BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_staff_email ON staff_users(email);
CREATE INDEX idx_staff_role ON staff_users(role);

-- AI Knowledge Base (for RAG)
CREATE TABLE IF NOT EXISTS knowledge_base_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Classification
    category VARCHAR(100) NOT NULL,
    -- property_info, area_info, policy, faq, troubleshooting
    
    -- Content
    question TEXT,
    answer TEXT NOT NULL,
    keywords TEXT[],
    
    -- Context
    property_id UUID REFERENCES properties(id) ON DELETE CASCADE,
    -- NULL = general knowledge (applies to all properties)
    
    -- Vector Embedding (stored in Qdrant, reference here)
    qdrant_point_id UUID,
    
    -- Usage
    usage_count INTEGER DEFAULT 0,
    helpful_count INTEGER DEFAULT 0,
    not_helpful_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    
    -- Metadata
    is_active BOOLEAN DEFAULT true,
    source VARCHAR(100), -- manual, imported, ai_generated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_knowledge_category ON knowledge_base_entries(category);
CREATE INDEX idx_knowledge_property_id ON knowledge_base_entries(property_id);
CREATE INDEX idx_knowledge_active ON knowledge_base_entries(is_active);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Current Guests View
CREATE OR REPLACE VIEW current_guests AS
SELECT 
    g.*,
    r.id as reservation_id,
    r.confirmation_code,
    r.check_in_date,
    r.check_out_date,
    r.status as reservation_status,
    p.name as property_name,
    p.wifi_ssid,
    p.wifi_password
FROM guests g
JOIN reservations r ON g.id = r.guest_id
JOIN properties p ON r.property_id = p.id
WHERE r.status = 'checked_in'
  AND CURRENT_DATE BETWEEN r.check_in_date AND r.check_out_date;

-- Guests Arriving Today
CREATE OR REPLACE VIEW guests_arriving_today AS
SELECT 
    g.*,
    r.id as reservation_id,
    r.confirmation_code,
    r.check_in_date,
    r.check_out_date,
    p.name as property_name,
    p.access_code_type,
    r.access_code
FROM guests g
JOIN reservations r ON g.id = r.guest_id
JOIN properties p ON r.property_id = p.id
WHERE r.check_in_date = CURRENT_DATE
  AND r.status = 'confirmed';

-- Guests Departing Today
CREATE OR REPLACE VIEW guests_departing_today AS
SELECT 
    g.*,
    r.id as reservation_id,
    r.confirmation_code,
    r.check_in_date,
    r.check_out_date,
    p.name as property_name
FROM guests g
JOIN reservations r ON g.id = r.guest_id
JOIN properties p ON r.property_id = p.id
WHERE r.check_out_date = CURRENT_DATE
  AND r.status IN ('confirmed', 'checked_in');

-- Message Thread View (conversation history)
CREATE OR REPLACE VIEW message_threads AS
SELECT 
    m.guest_id,
    g.phone_number,
    g.first_name,
    g.last_name,
    MAX(m.created_at) as last_message_at,
    COUNT(*) as message_count,
    COUNT(*) FILTER (WHERE m.direction = 'inbound' AND m.read_at IS NULL) as unread_count
FROM messages m
LEFT JOIN guests g ON m.guest_id = g.id
GROUP BY m.guest_id, g.phone_number, g.first_name, g.last_name;

-- Dashboard Stats View
CREATE OR REPLACE VIEW dashboard_stats AS
SELECT
    (SELECT COUNT(*) FROM reservations WHERE check_in_date = CURRENT_DATE AND status = 'confirmed') as guests_arriving_today,
    (SELECT COUNT(*) FROM reservations WHERE status = 'checked_in' AND CURRENT_DATE BETWEEN check_in_date AND check_out_date) as guests_currently_staying,
    (SELECT COUNT(*) FROM reservations WHERE check_out_date = CURRENT_DATE AND status IN ('confirmed', 'checked_in')) as guests_departing_today,
    (SELECT COUNT(*) FROM reservations WHERE check_in_date >= CURRENT_DATE - INTERVAL '30 days') as guests_last_30_days,
    (SELECT COUNT(*) FROM messages WHERE created_at::DATE = CURRENT_DATE) as messages_today,
    (SELECT COUNT(*) FROM messages WHERE direction = 'outbound' AND is_auto_response = true AND created_at::DATE = CURRENT_DATE) as ai_responses_today,
    (SELECT COUNT(*) FROM work_orders WHERE status IN ('open', 'in_progress')) as open_work_orders,
    (SELECT AVG(guest_rating) FROM reservations WHERE guest_rating IS NOT NULL AND created_at >= CURRENT_DATE - INTERVAL '30 days') as avg_rating_30_days;

-- ============================================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================================

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at triggers
CREATE TRIGGER update_properties_updated_at BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_guests_updated_at BEFORE UPDATE ON guests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_reservations_updated_at BEFORE UPDATE ON reservations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Auto-generate work order ticket numbers
CREATE OR REPLACE FUNCTION generate_ticket_number()
RETURNS TRIGGER AS $$
BEGIN
    NEW.ticket_number = 'WO-' || TO_CHAR(CURRENT_DATE, 'YYYYMMDD') || '-' || LPAD(nextval('work_order_seq')::TEXT, 4, '0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE SEQUENCE IF NOT EXISTS work_order_seq;

CREATE TRIGGER generate_work_order_ticket_number BEFORE INSERT ON work_orders
    FOR EACH ROW EXECUTE FUNCTION generate_ticket_number();

-- ============================================================================
-- SEED DATA
-- ============================================================================
-- Properties, reservations, and guests are synced from Streamline VRS.
-- See: seed_production.sql for staff, templates, knowledge base, and extras.
-- ============================================================================

INSERT INTO staff_users (email, password_hash, first_name, last_name, role, notification_email)
VALUES 
    ('lissa@cabin-rentals-of-georgia.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIeWJ4.daa', 'Lissa', 'Knight', 'admin', 'lissa@cabin-rentals-of-georgia.com')
ON CONFLICT (email) DO NOTHING;

-- ============================================================================
-- AGENT RESPONSE QUEUE (human-in-the-loop review for AI responses)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_response_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    guest_id        UUID REFERENCES guests(id) ON DELETE SET NULL,
    reservation_id  UUID REFERENCES reservations(id) ON DELETE SET NULL,

    -- Classification
    intent          VARCHAR(50),
    sentiment_label VARCHAR(30),
    sentiment_score FLOAT,
    urgency_level   INTEGER DEFAULT 0,

    -- Proposed response
    proposed_response TEXT NOT NULL,
    confidence      FLOAT NOT NULL DEFAULT 0.0,
    action          VARCHAR(80),
    escalation_reason TEXT,

    -- Review workflow
    status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    reviewed_by     VARCHAR(100),
    reviewed_at     TIMESTAMP,
    final_response  TEXT,
    sent_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,

    -- Metadata
    decision_metadata JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arq_status ON agent_response_queue(status);
CREATE INDEX IF NOT EXISTS idx_arq_created ON agent_response_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_arq_message ON agent_response_queue(message_id);
CREATE INDEX IF NOT EXISTS idx_arq_guest ON agent_response_queue(guest_id);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_messages_body_search ON messages USING gin(to_tsvector('english', body));
CREATE INDEX IF NOT EXISTS idx_knowledge_answer_search ON knowledge_base_entries USING gin(to_tsvector('english', answer));

-- ============================================================================
-- PERMISSIONS (for application user)
-- ============================================================================

-- Create application role if needed
-- CREATE ROLE fgp_app WITH LOGIN PASSWORD 'your_secure_password';
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO fgp_app;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO fgp_app;

-- ============================================================================
-- SCHEMA COMPLETE
-- ============================================================================
