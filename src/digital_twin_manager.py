"""
Fortress Digital Twin Manager — Redpanda-to-PostgreSQL State Sync

Consumes IoT events from Redpanda and UPSERTs the corresponding rows in
``iot_schema.digital_twins`` (fortress_guest database).  The FGP API reads
from the same table via async SQLAlchemy, giving the Command Center a
zero-latency view of every physical device.

Usage:
    python -m src.digital_twin_manager
"""

import asyncio
import json
import logging
import os
import signal

import psycopg2
from psycopg2.extras import Json, execute_values
from aiokafka import AIOKafkaConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("digital_twin_manager")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "digital_twin_sync_v1"

# Targets the FGP database where the iot_schema lives.
FGP_DB_HOST = os.getenv("FGP_DB_HOST", os.getenv("DB_HOST", "192.168.0.100"))
FGP_DB_PORT = int(os.getenv("FGP_DB_PORT", os.getenv("DB_PORT", "5432")))
FGP_DB_NAME = os.getenv("FGP_DB_NAME", "fortress_guest")
FGP_DB_USER = os.getenv("FGP_DB_USER", os.getenv("DB_USER", ""))
FGP_DB_PASS = os.getenv("FGP_DB_PASS", os.getenv("DB_PASS", ""))

SUBSCRIBED_TOPICS = [
    "iot.locks.state_changed",
    "iot.thermostat.state_changed",
    "system.health.alerts",
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(
        host=FGP_DB_HOST,
        port=FGP_DB_PORT,
        dbname=FGP_DB_NAME,
        user=FGP_DB_USER,
        password=FGP_DB_PASS,
    )


def _upsert_twin(device_id: str, device_type: str, state_json: dict, battery: int | None = None):
    """UPSERT a single digital twin row and append an audit event."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            battery_clause = ""
            params: list = [device_id, device_type, Json(state_json)]

            if battery is not None:
                battery_clause = ", battery_level = %(battery)s"

            cur.execute(
                """
                INSERT INTO iot_schema.digital_twins
                    (device_id, property_id, device_type, state_json, updated_at, last_event_ts)
                VALUES
                    (%(did)s, 'unassigned', %(dtype)s, %(state)s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (device_id) DO UPDATE SET
                    state_json    = EXCLUDED.state_json,
                    device_type   = EXCLUDED.device_type,
                    last_event_ts = CURRENT_TIMESTAMP,
                    updated_at    = CURRENT_TIMESTAMP
                """
                + (", battery_level = %(battery)s" if battery is not None else ""),
                {"did": device_id, "dtype": device_type, "state": Json(state_json), "battery": battery},
            )

            cur.execute(
                """
                INSERT INTO iot_schema.device_events (device_id, event_type, payload)
                VALUES (%s, %s, %s)
                """,
                (device_id, device_type, Json(state_json)),
            )

            conn.commit()
    except Exception as exc:
        log.error("DB upsert failed for %s: %s", device_id, exc)
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def handle_lock_event(payload: dict):
    device_id = payload.get("device_id")
    state = payload.get("state")
    if not device_id:
        return

    state_json = {
        "lock_state": state,
        "raw_zwave_value": payload.get("raw_zwave_value"),
        "timestamp": payload.get("timestamp"),
    }

    await asyncio.to_thread(_upsert_twin, device_id, "smart_lock", state_json)
    log.info("[DIGITAL TWIN] %s -> %s", device_id, state)


async def handle_thermostat_event(payload: dict):
    device_id = payload.get("device_id")
    if not device_id:
        return

    state_json = {
        "temperature": payload.get("temperature"),
        "state": payload.get("state"),
        "timestamp": payload.get("timestamp"),
    }

    await asyncio.to_thread(_upsert_twin, device_id, "thermostat", state_json)
    log.info("[DIGITAL TWIN] %s -> %.1f°F", device_id, payload.get("temperature", 0))


async def handle_health_alert(payload: dict):
    if payload.get("type") != "iot_battery_update":
        return

    data = payload.get("data", {})
    device_id = data.get("device_id")
    battery = data.get("battery")
    if not device_id or battery is None:
        return

    state_json = {"battery_update": True, "battery": battery, "timestamp": data.get("timestamp")}
    await asyncio.to_thread(_upsert_battery, device_id, battery, state_json)
    log.info("[DIGITAL TWIN] Battery update %s -> %d%%", device_id, battery)


def _upsert_battery(device_id: str, battery: int, state_json: dict):
    """Update battery level on an existing twin without overwriting device_type or state_json."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE iot_schema.digital_twins
                SET battery_level = %s, updated_at = CURRENT_TIMESTAMP
                WHERE device_id = %s
                """,
                (battery, device_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    """
                    INSERT INTO iot_schema.digital_twins
                        (device_id, property_id, device_type, state_json, battery_level, updated_at, last_event_ts)
                    VALUES (%s, 'unassigned', 'smart_lock', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (device_id) DO UPDATE SET
                        battery_level = EXCLUDED.battery_level,
                        updated_at    = CURRENT_TIMESTAMP
                    """,
                    (device_id, Json(state_json), battery),
                )
            cur.execute(
                """
                INSERT INTO iot_schema.device_events (device_id, event_type, payload)
                VALUES (%s, 'battery_update', %s)
                """,
                (device_id, Json(state_json)),
            )
            conn.commit()
    except Exception as exc:
        log.error("DB battery update failed for %s: %s", device_id, exc)
        conn.rollback()
    finally:
        conn.close()


TOPIC_HANDLERS = {
    "iot.locks.state_changed": handle_lock_event,
    "iot.thermostat.state_changed": handle_thermostat_event,
    "system.health.alerts": handle_health_alert,
}


# ---------------------------------------------------------------------------
# Consumer loop
# ---------------------------------------------------------------------------

async def consume_iot_events():
    consumer = AIOKafkaConsumer(
        *SUBSCRIBED_TOPICS,
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    await consumer.start()
    log.info("Digital Twin Manager online — consuming from Redpanda [%s]", ", ".join(SUBSCRIBED_TOPICS))

    try:
        async for msg in consumer:
            handler = TOPIC_HANDLERS.get(msg.topic)
            if handler:
                try:
                    await handler(msg.value)
                except Exception as exc:
                    log.error("Handler error on topic %s: %s", msg.topic, exc)
    finally:
        await consumer.stop()
        log.info("Redpanda consumer stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown()))
    await consume_iot_events()


async def _shutdown():
    log.info("Graceful shutdown requested.")
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Digital Twin Manager.")
