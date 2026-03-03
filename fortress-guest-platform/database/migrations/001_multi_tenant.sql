-- ============================================================================
-- Migration 001: Multi-Tenant Support
-- Adds tenant_id to all tables, creates tenants table, and enables RLS
-- ============================================================================

BEGIN;

-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    domain VARCHAR(255),
    logo_url TEXT,
    primary_color VARCHAR(7) DEFAULT '#1e40af',
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    
    -- Streamline VRS credentials (per-tenant)
    streamline_api_url TEXT,
    streamline_api_key TEXT,
    streamline_api_secret TEXT,
    
    -- Twilio credentials (per-tenant)
    twilio_account_sid VARCHAR(100),
    twilio_auth_token VARCHAR(255),
    twilio_phone_number VARCHAR(20),
    
    -- Subscription
    plan VARCHAR(50) DEFAULT 'starter',  -- starter, professional, enterprise
    max_properties INTEGER DEFAULT 25,
    max_staff_users INTEGER DEFAULT 5,
    is_active BOOLEAN DEFAULT true,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed CROG as tenant #1
INSERT INTO tenants (name, slug, domain, timezone, plan, max_properties, max_staff_users)
VALUES (
    'Cabin Rentals of Georgia',
    'crog',
    'cabin-rentals-of-georgia.com',
    'America/New_York',
    'enterprise',
    50,
    20
)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- Add tenant_id to all core tables
-- ============================================================================

DO $$
DECLARE
    crog_id UUID;
    tbl TEXT;
BEGIN
    SELECT id INTO crog_id FROM tenants WHERE slug = 'crog';

    FOREACH tbl IN ARRAY ARRAY[
        'properties', 'guests', 'reservations', 'messages',
        'message_templates', 'work_orders', 'staff_users',
        'guestbook_guides', 'knowledge_base_entries', 'extras',
        'extra_orders', 'agent_response_queue'
    ]
    LOOP
        -- Add column if it doesn't exist
        EXECUTE format(
            'ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)',
            tbl
        );
        -- Backfill existing rows to CROG
        EXECUTE format(
            'UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL',
            tbl, crog_id
        );
        -- Create index
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_%I_tenant ON %I(tenant_id)',
            tbl, tbl
        );
    END LOOP;
END;
$$;

-- ============================================================================
-- Row-Level Security (RLS)
-- ============================================================================

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'properties', 'guests', 'reservations', 'messages',
        'message_templates', 'work_orders', 'staff_users',
        'guestbook_guides', 'knowledge_base_entries', 'extras',
        'extra_orders', 'agent_response_queue'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);

        -- Drop existing policies if they exist, then recreate
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_%I ON %I', tbl, tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_%I ON %I
             USING (tenant_id::text = current_setting(''app.current_tenant_id'', true))',
            tbl, tbl
        );

        EXECUTE format('DROP POLICY IF EXISTS superuser_bypass_%I ON %I', tbl, tbl);
        EXECUTE format(
            'CREATE POLICY superuser_bypass_%I ON %I
             USING (current_setting(''app.current_tenant_id'', true) IS NULL
                    OR current_setting(''app.current_tenant_id'', true) = '''')',
            tbl, tbl
        );
    END LOOP;
END;
$$;

COMMIT;
