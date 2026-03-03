-- ============================================================================
-- Migration 004: Digital Twin Schema (Division 1 — Physical Automation)
--
-- Persistent replica of all IoT device states. The Z-Wave MQTT bridge
-- publishes events to Redpanda; the Digital Twin Manager consumes them
-- and UPSERTs rows here.  The FGP API serves reads from this table at
-- zero latency — no polling of the physical Z-Wave mesh.
-- ============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS iot_schema;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Primary twin table: one row per physical device
CREATE TABLE IF NOT EXISTS iot_schema.digital_twins (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id       VARCHAR(100) UNIQUE NOT NULL,
    property_id     VARCHAR(100) NOT NULL DEFAULT 'unassigned',
    device_type     VARCHAR(50)  NOT NULL,
    device_name     VARCHAR(255),
    state_json      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    battery_level   INT          DEFAULT 100,
    is_online       BOOLEAN      DEFAULT TRUE,
    last_event_ts   TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP,
    created_at      TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_twins_property    ON iot_schema.digital_twins(property_id);
CREATE INDEX IF NOT EXISTS idx_twins_device      ON iot_schema.digital_twins(device_id);
CREATE INDEX IF NOT EXISTS idx_twins_device_type ON iot_schema.digital_twins(device_type);

-- Audit log: recent state-change events per device (bounded by application)
CREATE TABLE IF NOT EXISTS iot_schema.device_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id   VARCHAR(100) NOT NULL,
    event_type  VARCHAR(100) NOT NULL,
    payload     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_device_events_device  ON iot_schema.device_events(device_id);
CREATE INDEX IF NOT EXISTS idx_device_events_created ON iot_schema.device_events(created_at DESC);

COMMIT;
