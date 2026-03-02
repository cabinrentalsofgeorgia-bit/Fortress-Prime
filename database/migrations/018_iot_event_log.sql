-- Migration 018: IoT Nervous System — Physical-to-Digital Schema
-- Effective: 2026-03-01
-- Purpose: Bridge physical Z-Wave devices to the Fortress property graph
--          and create the reservation-aware event log consumed by the
--          Chargeback Ironclad dispute defense engine.

BEGIN;

-- =========================================================================
-- Table 1: iot_device_map — The Rosetta Stone
-- Maps physical Z-Wave node IDs / MAC addresses to Fortress property UUIDs.
-- =========================================================================

CREATE TABLE IF NOT EXISTS iot_device_map (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       VARCHAR(100) NOT NULL UNIQUE,
    zwave_node_id   VARCHAR(50),
    mac_address     VARCHAR(20),
    property_id     UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    device_type     VARCHAR(50) NOT NULL DEFAULT 'smart_lock',
    device_name     VARCHAR(255),
    location        VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_device_map_property ON iot_device_map(property_id);
CREATE INDEX IF NOT EXISTS idx_device_map_zwave_node ON iot_device_map(zwave_node_id) WHERE zwave_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_device_map_active ON iot_device_map(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE iot_device_map IS 'Maps physical Z-Wave device identifiers to Fortress property UUIDs';
COMMENT ON COLUMN iot_device_map.device_id IS 'Logical device ID matching digital_twins.device_id (e.g. FrontDoorLock_CabinA)';
COMMENT ON COLUMN iot_device_map.zwave_node_id IS 'Raw Z-Wave node number extracted from MQTT topic path';
COMMENT ON COLUMN iot_device_map.location IS 'Physical location on property: front_door, back_door, garage, etc.';

-- =========================================================================
-- Table 2: iot_event_log — The Golden Record
-- Reservation-aware event log that the dispute defense engine queries.
-- Schema matches the existing queries in dispute_webhooks.py and
-- dispute_defense.py exactly.
-- =========================================================================

CREATE TABLE IF NOT EXISTS iot_event_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       VARCHAR(100) NOT NULL,
    property_id     UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    reservation_id  UUID REFERENCES reservations(id) ON DELETE SET NULL,
    event_type      VARCHAR(50) NOT NULL,
    user_code       VARCHAR(20),
    timestamp       TIMESTAMPTZ NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_iot_event_property_ts ON iot_event_log(property_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_iot_event_reservation ON iot_event_log(reservation_id) WHERE reservation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_iot_event_device_ts ON iot_event_log(device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_iot_event_type ON iot_event_log(event_type);

COMMENT ON TABLE iot_event_log IS 'Reservation-aware IoT event log — consumed by the Chargeback Ironclad dispute defense engine';
COMMENT ON COLUMN iot_event_log.event_type IS 'lock, unlock, code_set, code_used, code_revoked';
COMMENT ON COLUMN iot_event_log.user_code IS 'Keypad code used, matched against reservations.access_code';
COMMENT ON COLUMN iot_event_log.metadata IS 'Raw Z-Wave payload including raw_zwave_value, battery, etc.';

-- =========================================================================
-- Backfill: Update digital_twins property_id from iot_device_map
-- This trigger keeps digital_twins.property_id in sync with the device map.
-- =========================================================================

CREATE OR REPLACE FUNCTION sync_twin_property_id()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE iot_schema.digital_twins
    SET property_id = NEW.property_id::text
    WHERE device_id = NEW.device_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_device_map_sync_twin ON iot_device_map;
CREATE TRIGGER trg_device_map_sync_twin
    AFTER INSERT OR UPDATE OF property_id ON iot_device_map
    FOR EACH ROW
    EXECUTE FUNCTION sync_twin_property_id();

COMMIT;
