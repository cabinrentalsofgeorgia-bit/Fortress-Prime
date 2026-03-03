-- ============================================================================
-- Migration 002: Enterprise Guest Management System
-- Fortress Guest Platform
-- 
-- NEW TABLES: guest_verifications, guest_reviews, guest_surveys,
--             survey_templates, rental_agreements, agreement_templates,
--             guest_activities
-- ALTERED: guests (massive column additions)
-- ============================================================================

-- ════════════════════════════════════════════════════════════════
-- ALTER guests table - Add enterprise columns
-- ════════════════════════════════════════════════════════════════

-- Secondary contact
ALTER TABLE guests ADD COLUMN IF NOT EXISTS phone_number_secondary VARCHAR(20);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS email_secondary VARCHAR(255);

-- Address
ALTER TABLE guests ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(255);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS state VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS country VARCHAR(2) DEFAULT 'US';

-- Demographics
ALTER TABLE guests ADD COLUMN IF NOT EXISTS date_of_birth DATE;

-- Emergency contact
ALTER TABLE guests ADD COLUMN IF NOT EXISTS emergency_contact_name VARCHAR(200);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS emergency_contact_phone VARCHAR(20);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS emergency_contact_relationship VARCHAR(50);

-- Vehicle
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vehicle_make VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vehicle_model VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vehicle_color VARCHAR(30);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vehicle_plate VARCHAR(20);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vehicle_state VARCHAR(5);

-- Communication preferences (enhanced)
ALTER TABLE guests ADD COLUMN IF NOT EXISTS opt_in_sms BOOLEAN DEFAULT true;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS opt_in_email BOOLEAN DEFAULT true;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS quiet_hours_start VARCHAR(5);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS quiet_hours_end VARCHAR(5);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) DEFAULT 'America/New_York';

-- Identity verification
ALTER TABLE guests ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'unverified';
ALTER TABLE guests ADD COLUMN IF NOT EXISTS verification_method VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS id_document_type VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS id_expiration_date DATE;

-- Loyalty program
ALTER TABLE guests ADD COLUMN IF NOT EXISTS loyalty_tier VARCHAR(20) DEFAULT 'bronze';
ALTER TABLE guests ADD COLUMN IF NOT EXISTS loyalty_points INTEGER DEFAULT 0;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS loyalty_enrolled_at TIMESTAMP;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS lifetime_stays INTEGER DEFAULT 0;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS lifetime_nights INTEGER DEFAULT 0;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS lifetime_revenue DECIMAL(12,2) DEFAULT 0;

-- Scoring
ALTER TABLE guests ADD COLUMN IF NOT EXISTS value_score INTEGER DEFAULT 50;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS risk_score INTEGER DEFAULT 10;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS satisfaction_score INTEGER;

-- Preferences
ALTER TABLE guests ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}';

-- Notes (enhanced)
ALTER TABLE guests ADD COLUMN IF NOT EXISTS special_requests TEXT;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS internal_notes TEXT;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS staff_notes TEXT;

-- Flags
ALTER TABLE guests ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT false;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS is_blacklisted BOOLEAN DEFAULT false;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS blacklist_reason TEXT;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS blacklisted_at TIMESTAMP;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS blacklisted_by VARCHAR(100);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS is_do_not_contact BOOLEAN DEFAULT false;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS requires_supervision BOOLEAN DEFAULT false;

-- Source & attribution
ALTER TABLE guests ADD COLUMN IF NOT EXISTS guest_source VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS referral_source VARCHAR(255);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS first_booking_source VARCHAR(50);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS acquisition_campaign VARCHAR(100);

-- External IDs
ALTER TABLE guests ADD COLUMN IF NOT EXISTS airbnb_guest_id VARCHAR(100);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS vrbo_guest_id VARCHAR(100);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS booking_com_guest_id VARCHAR(100);
ALTER TABLE guests ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(100);

-- Activity timestamps
ALTER TABLE guests ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMP;
ALTER TABLE guests ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP;

-- New indexes
CREATE INDEX IF NOT EXISTS idx_guests_loyalty_tier ON guests(loyalty_tier);
CREATE INDEX IF NOT EXISTS idx_guests_verification_status ON guests(verification_status);
CREATE INDEX IF NOT EXISTS idx_guests_is_vip ON guests(is_vip);
CREATE INDEX IF NOT EXISTS idx_guests_is_blacklisted ON guests(is_blacklisted);
CREATE INDEX IF NOT EXISTS idx_guests_guest_source ON guests(guest_source);
CREATE INDEX IF NOT EXISTS idx_guests_value_score ON guests(value_score DESC);
CREATE INDEX IF NOT EXISTS idx_guests_city_state ON guests(city, state);

-- ════════════════════════════════════════════════════════════════
-- Guest Verifications
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS guest_verifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    
    verification_type VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    
    document_type VARCHAR(50),
    document_number_hash VARCHAR(255),
    document_country VARCHAR(2),
    document_state VARCHAR(5),
    document_expiration DATE,
    document_front_url TEXT,
    document_back_url TEXT,
    selfie_url TEXT,
    
    confidence_score DECIMAL(4,3),
    match_details JSONB,
    
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    rejection_reason TEXT,
    
    external_verification_id VARCHAR(255),
    provider VARCHAR(50),
    
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gv_guest_id ON guest_verifications(guest_id);
CREATE INDEX IF NOT EXISTS idx_gv_status ON guest_verifications(status);

-- ════════════════════════════════════════════════════════════════
-- Guest Reviews (bidirectional)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS guest_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    
    direction VARCHAR(30) NOT NULL, -- guest_to_property, property_to_guest
    overall_rating INTEGER NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
    
    -- Guest reviewing property
    cleanliness_rating INTEGER CHECK (cleanliness_rating BETWEEN 1 AND 5),
    accuracy_rating INTEGER CHECK (accuracy_rating BETWEEN 1 AND 5),
    communication_rating INTEGER CHECK (communication_rating BETWEEN 1 AND 5),
    location_rating INTEGER CHECK (location_rating BETWEEN 1 AND 5),
    checkin_rating INTEGER CHECK (checkin_rating BETWEEN 1 AND 5),
    value_rating INTEGER CHECK (value_rating BETWEEN 1 AND 5),
    amenities_rating INTEGER CHECK (amenities_rating BETWEEN 1 AND 5),
    
    -- Manager reviewing guest
    house_rules_rating INTEGER CHECK (house_rules_rating BETWEEN 1 AND 5),
    cleanliness_left_rating INTEGER CHECK (cleanliness_left_rating BETWEEN 1 AND 5),
    communication_guest_rating INTEGER CHECK (communication_guest_rating BETWEEN 1 AND 5),
    respect_rating INTEGER CHECK (respect_rating BETWEEN 1 AND 5),
    noise_rating INTEGER CHECK (noise_rating BETWEEN 1 AND 5),
    checkout_compliance_rating INTEGER CHECK (checkout_compliance_rating BETWEEN 1 AND 5),
    
    title VARCHAR(255),
    body TEXT,
    
    response_body TEXT,
    response_by VARCHAR(100),
    response_at TIMESTAMP,
    
    sentiment VARCHAR(20),
    sentiment_score DECIMAL(4,3),
    key_phrases JSONB,
    improvement_suggestions JSONB,
    
    is_published BOOLEAN DEFAULT false,
    published_at TIMESTAMP,
    publish_to_website BOOLEAN DEFAULT true,
    publish_to_airbnb BOOLEAN DEFAULT false,
    publish_to_google BOOLEAN DEFAULT false,
    external_review_urls JSONB,
    
    is_flagged BOOLEAN DEFAULT false,
    flag_reason VARCHAR(255),
    moderated_by VARCHAR(100),
    moderated_at TIMESTAMP,
    
    solicitation_sent_at TIMESTAMP,
    solicitation_method VARCHAR(20),
    solicitation_template_id UUID,
    submitted_via VARCHAR(30),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gr_guest_id ON guest_reviews(guest_id);
CREATE INDEX IF NOT EXISTS idx_gr_property_id ON guest_reviews(property_id);
CREATE INDEX IF NOT EXISTS idx_gr_direction ON guest_reviews(direction);
CREATE INDEX IF NOT EXISTS idx_gr_rating ON guest_reviews(overall_rating);
CREATE INDEX IF NOT EXISTS idx_gr_published ON guest_reviews(is_published);

-- ════════════════════════════════════════════════════════════════
-- Survey Templates
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS survey_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    survey_type VARCHAR(50) NOT NULL,
    questions JSONB NOT NULL,
    
    trigger_type VARCHAR(50),
    trigger_offset_hours INTEGER,
    send_method VARCHAR(20) DEFAULT 'sms',
    
    is_active BOOLEAN DEFAULT true,
    usage_count INTEGER DEFAULT 0,
    avg_completion_rate DECIMAL(5,2),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_st_type ON survey_templates(survey_type);
CREATE INDEX IF NOT EXISTS idx_st_active ON survey_templates(is_active);

-- ════════════════════════════════════════════════════════════════
-- Guest Surveys (responses)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS guest_surveys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    template_id UUID REFERENCES survey_templates(id) ON DELETE SET NULL,
    
    survey_type VARCHAR(50) NOT NULL,
    responses JSONB NOT NULL DEFAULT '{}',
    
    overall_score DECIMAL(4,2),
    nps_score INTEGER,
    nps_category VARCHAR(20),
    
    housekeeping_score INTEGER,
    maintenance_score INTEGER,
    communication_score INTEGER,
    amenities_score INTEGER,
    
    sentiment VARCHAR(20),
    key_themes JSONB,
    action_items JSONB,
    
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    sent_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    send_method VARCHAR(20),
    survey_url TEXT,
    
    follow_up_required BOOLEAN DEFAULT false,
    follow_up_notes TEXT,
    follow_up_completed_at TIMESTAMP,
    follow_up_by VARCHAR(100),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gs_guest_id ON guest_surveys(guest_id);
CREATE INDEX IF NOT EXISTS idx_gs_status ON guest_surveys(status);
CREATE INDEX IF NOT EXISTS idx_gs_type ON guest_surveys(survey_type);
CREATE INDEX IF NOT EXISTS idx_gs_nps ON guest_surveys(nps_category);

-- ════════════════════════════════════════════════════════════════
-- Agreement Templates
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agreement_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    agreement_type VARCHAR(50) NOT NULL,
    
    content_markdown TEXT NOT NULL,
    required_variables JSONB,
    
    is_active BOOLEAN DEFAULT true,
    requires_signature BOOLEAN DEFAULT true,
    requires_initials BOOLEAN DEFAULT false,
    auto_send BOOLEAN DEFAULT true,
    send_days_before_checkin INTEGER DEFAULT 7,
    property_ids JSONB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_at_type ON agreement_templates(agreement_type);
CREATE INDEX IF NOT EXISTS idx_at_active ON agreement_templates(is_active);

-- ════════════════════════════════════════════════════════════════
-- Rental Agreements
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS rental_agreements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    template_id UUID REFERENCES agreement_templates(id) ON DELETE SET NULL,
    
    agreement_type VARCHAR(50) NOT NULL,
    rendered_content TEXT NOT NULL,
    
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    
    sent_at TIMESTAMP,
    sent_via VARCHAR(20),
    agreement_url TEXT,
    expires_at TIMESTAMP,
    
    first_viewed_at TIMESTAMP,
    view_count INTEGER DEFAULT 0,
    
    signed_at TIMESTAMP,
    signature_type VARCHAR(30),
    signature_data TEXT,
    signer_name VARCHAR(200),
    signer_email VARCHAR(255),
    
    initials_data TEXT,
    initials_pages JSONB,
    
    signer_ip_address VARCHAR(45),
    signer_user_agent TEXT,
    signer_device_fingerprint VARCHAR(255),
    consent_recorded BOOLEAN DEFAULT false,
    
    pdf_url TEXT,
    pdf_generated_at TIMESTAMP,
    
    reminder_count INTEGER DEFAULT 0,
    last_reminder_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ra_guest_id ON rental_agreements(guest_id);
CREATE INDEX IF NOT EXISTS idx_ra_reservation_id ON rental_agreements(reservation_id);
CREATE INDEX IF NOT EXISTS idx_ra_status ON rental_agreements(status);

-- ════════════════════════════════════════════════════════════════
-- Guest Activities (timeline)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS guest_activities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    
    activity_type VARCHAR(50) NOT NULL,
    category VARCHAR(30) NOT NULL,
    
    title VARCHAR(255) NOT NULL,
    description TEXT,
    
    reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    message_id UUID,
    review_id UUID,
    survey_id UUID,
    agreement_id UUID,
    work_order_id UUID,
    
    performed_by VARCHAR(100),
    performed_by_type VARCHAR(20),
    
    metadata JSONB,
    importance VARCHAR(10) DEFAULT 'normal',
    is_visible_to_guest VARCHAR(5) DEFAULT 'false',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ga_guest_id ON guest_activities(guest_id);
CREATE INDEX IF NOT EXISTS idx_ga_type ON guest_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_ga_category ON guest_activities(category);
CREATE INDEX IF NOT EXISTS idx_ga_created_at ON guest_activities(created_at DESC);

-- ════════════════════════════════════════════════════════════════
-- SEED DATA - Default survey templates
-- ════════════════════════════════════════════════════════════════

INSERT INTO survey_templates (name, description, survey_type, questions, trigger_type, trigger_offset_hours, send_method)
VALUES 
    ('Post-Stay Survey', 'Comprehensive post-checkout guest survey', 'post_stay',
     '[
       {"id": "q1", "type": "rating", "question": "How would you rate your overall stay?", "required": true, "scale_min": 1, "scale_max": 5, "category": "overall"},
       {"id": "q2", "type": "rating", "question": "How clean was the property?", "required": true, "scale_min": 1, "scale_max": 5, "category": "cleanliness"},
       {"id": "q3", "type": "rating", "question": "How was the check-in experience?", "required": true, "scale_min": 1, "scale_max": 5, "category": "checkin"},
       {"id": "q4", "type": "rating", "question": "How responsive was our team?", "required": true, "scale_min": 1, "scale_max": 5, "category": "communication"},
       {"id": "q5", "type": "rating", "question": "How would you rate the amenities?", "required": true, "scale_min": 1, "scale_max": 5, "category": "amenities"},
       {"id": "q6", "type": "nps", "question": "How likely are you to recommend us to a friend? (0-10)", "required": true, "scale_min": 0, "scale_max": 10, "category": "nps"},
       {"id": "q7", "type": "multiple_choice", "question": "What was the highlight of your stay?", "options": ["Hot tub", "Mountain views", "Fireplace", "Game room", "Kitchen", "Location", "Cleanliness", "Other"], "allow_multiple": true, "category": "highlights"},
       {"id": "q8", "type": "text", "question": "Any suggestions for improvement?", "required": false, "category": "feedback"}
     ]'::jsonb,
     'auto_post_checkout', 48, 'sms')
ON CONFLICT (name) DO NOTHING;

INSERT INTO survey_templates (name, description, survey_type, questions, trigger_type, trigger_offset_hours, send_method)
VALUES 
    ('Mid-Stay Check-In', 'Quick mid-stay satisfaction check', 'mid_stay',
     '[
       {"id": "q1", "type": "rating", "question": "How is your stay going so far?", "required": true, "scale_min": 1, "scale_max": 5, "category": "overall"},
       {"id": "q2", "type": "yes_no", "question": "Is everything working properly?", "required": true, "category": "maintenance"},
       {"id": "q3", "type": "text", "question": "Is there anything we can help with?", "required": false, "category": "support"}
     ]'::jsonb,
     'auto_mid_stay', 48, 'sms')
ON CONFLICT (name) DO NOTHING;

-- Default agreement template
INSERT INTO agreement_templates (name, description, agreement_type, content_markdown, required_variables, requires_signature, auto_send, send_days_before_checkin)
VALUES 
    ('Standard Rental Agreement', 'Standard cabin rental agreement for CROG properties', 'rental_agreement',
     '# Rental Agreement

## Cabin Rentals of Georgia

This Rental Agreement ("Agreement") is entered into between **Cabin Rentals of Georgia** ("Property Manager") and **{{guest_name}}** ("Guest").

### Property
- **Property**: {{property_name}}
- **Address**: {{property_address}}

### Reservation Details
- **Confirmation Code**: {{confirmation_code}}
- **Check-In**: {{check_in_date}} at 4:00 PM EST
- **Check-Out**: {{check_out_date}} at 11:00 AM EST
- **Number of Guests**: {{num_guests}}
- **Total Amount**: ${{total_amount}}

### House Rules

1. **Maximum Occupancy**: The maximum number of guests shall not exceed {{max_guests}} persons.
2. **Quiet Hours**: Please observe quiet hours from 10:00 PM to 8:00 AM.
3. **No Smoking**: Smoking is strictly prohibited inside the property.
4. **Pets**: Pets are only allowed with prior approval and additional pet fee.
5. **Parking**: Park only in designated areas.
6. **Fires**: Use only designated fire pits. Never leave fires unattended.
7. **Trash**: All trash must be bagged and placed in bear-proof containers.

### Cancellation Policy
- 30+ days before check-in: Full refund minus processing fee
- 14-29 days: 50% refund
- Less than 14 days: No refund

### Damage Deposit
A security deposit may be held against the credit card on file. Any damages beyond normal wear and tear will be assessed and charged accordingly.

### Liability Waiver
Guest acknowledges that outdoor activities including hiking, hot tub use, and fire pit use carry inherent risks. Property Manager is not liable for personal injury during the stay.

### Agreement
By signing below, Guest acknowledges they have read, understand, and agree to abide by all terms of this Rental Agreement.

**Guest Signature**: ___________________________
**Date**: {{sign_date}}',
     '["guest_name", "property_name", "property_address", "confirmation_code", "check_in_date", "check_out_date", "num_guests", "total_amount", "max_guests", "sign_date"]'::jsonb,
     true, true, 7)
ON CONFLICT (name) DO NOTHING;

-- ════════════════════════════════════════════════════════════════
-- UPDATED VIEWS
-- ════════════════════════════════════════════════════════════════

-- Enhanced Dashboard Stats
CREATE OR REPLACE VIEW dashboard_stats AS
SELECT
    (SELECT COUNT(*) FROM reservations WHERE check_in_date = CURRENT_DATE AND status = 'confirmed') as guests_arriving_today,
    (SELECT COUNT(*) FROM reservations WHERE status = 'checked_in' AND CURRENT_DATE BETWEEN check_in_date AND check_out_date) as guests_currently_staying,
    (SELECT COUNT(*) FROM reservations WHERE check_out_date = CURRENT_DATE AND status IN ('confirmed', 'checked_in')) as guests_departing_today,
    (SELECT COUNT(*) FROM guests) as total_guests,
    (SELECT COUNT(*) FROM guests WHERE is_vip = true) as vip_guests,
    (SELECT COUNT(*) FROM guests WHERE lifetime_stays > 1) as repeat_guests,
    (SELECT COUNT(*) FROM guests WHERE is_blacklisted = true) as blacklisted_guests,
    (SELECT AVG(overall_rating) FROM guest_reviews WHERE direction = 'guest_to_property' AND created_at >= CURRENT_DATE - INTERVAL '30 days') as avg_review_rating_30d,
    (SELECT COUNT(*) FROM guest_reviews WHERE is_flagged = true AND response_body IS NULL) as reviews_needing_response,
    (SELECT COUNT(*) FROM rental_agreements WHERE status IN ('sent', 'viewed')) as unsigned_agreements,
    (SELECT COUNT(*) FROM messages WHERE created_at::DATE = CURRENT_DATE) as messages_today,
    (SELECT COUNT(*) FROM work_orders WHERE status IN ('open', 'in_progress')) as open_work_orders;

-- ════════════════════════════════════════════════════════════════
-- TRIGGERS
-- ════════════════════════════════════════════════════════════════

CREATE TRIGGER IF NOT EXISTS update_guest_verifications_updated_at BEFORE UPDATE ON guest_verifications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER IF NOT EXISTS update_guest_reviews_updated_at BEFORE UPDATE ON guest_reviews
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER IF NOT EXISTS update_guest_surveys_updated_at BEFORE UPDATE ON guest_surveys
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER IF NOT EXISTS update_rental_agreements_updated_at BEFORE UPDATE ON rental_agreements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER IF NOT EXISTS update_survey_templates_updated_at BEFORE UPDATE ON survey_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER IF NOT EXISTS update_agreement_templates_updated_at BEFORE UPDATE ON agreement_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ════════════════════════════════════════════════════════════════
-- MIGRATION COMPLETE
-- ════════════════════════════════════════════════════════════════
