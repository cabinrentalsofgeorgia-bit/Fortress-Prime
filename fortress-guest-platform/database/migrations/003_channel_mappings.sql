-- ============================================================================
-- Migration 003: Channel Manager Mappings
-- Maps properties to their listing IDs on each OTA channel
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS channel_mappings (
    id SERIAL PRIMARY KEY,
    property_id VARCHAR(100) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    listing_id VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    last_synced_at TIMESTAMP,
    sync_status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(property_id, channel)
);

CREATE INDEX idx_channel_mappings_property ON channel_mappings(property_id);
CREATE INDEX idx_channel_mappings_channel ON channel_mappings(channel);

-- Channel sync log (audit trail for all push/pull operations)
CREATE TABLE IF NOT EXISTS channel_sync_log (
    id SERIAL PRIMARY KEY,
    property_id VARCHAR(100),
    channel VARCHAR(50) NOT NULL,
    operation VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_channel_sync_log_channel ON channel_sync_log(channel, created_at);

COMMIT;
