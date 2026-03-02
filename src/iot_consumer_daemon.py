"""
IoT Consumer Daemon — Reservation-Aware Lock Event Writer

Subscribes to the Redpanda ``iot.locks.state_changed`` topic and for each
lock event:

  1. Resolve the property via ``iot_device_map`` (device_id -> property_id)
  2. Resolve the active reservation by matching access_code + date overlap,
     or by property_id + date overlap when no user code is available
  3. Determine event_type (code_used, unlock, lock)
  4. Write the golden record to ``iot_event_log``
  5. Manual offset commit after successful DB write (at-least-once delivery)

The ``iot_event_log`` table is the primary evidence source for the
Chargeback Ironclad dispute defense engine.

Usage:
    python3 src/iot_consumer_daemon.py
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone

import psycopg2
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("iot_consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
TOPIC = "iot.locks.state_changed"
GROUP_ID = "iot_event_log_writer_v1"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")


def get_db_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def resolve_property(conn, device_id: str):
    """Look up property_id from iot_device_map by device_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT property_id FROM iot_device_map WHERE device_id = %s AND is_active = TRUE LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None


def resolve_reservation(conn, property_id: str, event_ts: datetime, user_code: str = None):
    """
    Resolve the active reservation for a lock event.
    
    Strategy:
      1. If user_code is provided, match against reservations.access_code
         for the property with date overlap.
      2. If no user_code, find any confirmed reservation with date overlap.
    """
    with conn.cursor() as cur:
        if user_code:
            cur.execute(
                """
                SELECT id FROM reservations
                WHERE property_id::text = %s
                  AND access_code = %s
                  AND check_in_date <= %s
                  AND check_out_date >= %s
                  AND status NOT IN ('cancelled', 'no_show')
                ORDER BY check_in_date DESC
                LIMIT 1
                """,
                (property_id, user_code, event_ts.date(), event_ts.date()),
            )
        else:
            cur.execute(
                """
                SELECT id FROM reservations
                WHERE property_id::text = %s
                  AND check_in_date <= %s
                  AND check_out_date >= %s
                  AND status NOT IN ('cancelled', 'no_show')
                ORDER BY check_in_date DESC
                LIMIT 1
                """,
                (property_id, event_ts.date(), event_ts.date()),
            )
        row = cur.fetchone()
        return str(row[0]) if row else None


def determine_event_type(state: str, user_code: str = None) -> str:
    """Map Redpanda lock state to iot_event_log event_type."""
    if state == "unlocked":
        return "code_used" if user_code else "unlock"
    return "lock"


def write_event_log(conn, record: dict):
    """Insert a golden record into iot_event_log."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO iot_event_log
                (device_id, property_id, reservation_id, event_type,
                 user_code, timestamp, metadata)
            VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
            """,
            (
                record["device_id"],
                record["property_id"],
                record.get("reservation_id"),
                record["event_type"],
                record.get("user_code"),
                record["timestamp"],
                json.dumps(record.get("metadata", {})),
            ),
        )
    conn.commit()


async def consume():
    """Main consumer loop."""
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )

    await consumer.start()
    log.info("IoT Consumer started — group=%s topic=%s broker=%s", GROUP_ID, TOPIC, KAFKA_BROKER)

    conn = get_db_conn()
    log.info("Database connected — %s@%s/%s", DB_USER, DB_HOST, DB_NAME)

    events_processed = 0

    try:
        async for msg in consumer:
            try:
                payload = msg.value
                device_id = payload.get("device_id", "")
                state = payload.get("state", "")
                user_code = payload.get("user_code")
                raw_ts = payload.get("timestamp", "")

                if not device_id or not state:
                    log.warning("Malformed payload, skipping: %s", payload)
                    await consumer.commit()
                    continue

                try:
                    event_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    event_ts = datetime.now(timezone.utc)

                property_id = resolve_property(conn, device_id)
                if not property_id:
                    log.debug("No device mapping for %s, skipping", device_id)
                    await consumer.commit()
                    continue

                reservation_id = resolve_reservation(conn, property_id, event_ts, user_code)
                event_type = determine_event_type(state, user_code)

                record = {
                    "device_id": device_id,
                    "property_id": property_id,
                    "reservation_id": reservation_id,
                    "event_type": event_type,
                    "user_code": user_code,
                    "timestamp": event_ts.isoformat(),
                    "metadata": {
                        "raw_zwave_value": payload.get("raw_zwave_value"),
                        "device_type": payload.get("device_type"),
                        "source_state": state,
                    },
                }

                write_event_log(conn, record)
                await consumer.commit()

                events_processed += 1
                log.info(
                    "Event #%d written — device=%s property=%s type=%s reservation=%s",
                    events_processed,
                    device_id,
                    property_id[:8],
                    event_type,
                    (reservation_id[:8] + "...") if reservation_id else "none",
                )

            except psycopg2.Error as e:
                log.error("Database error processing event: %s", e)
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
                conn = get_db_conn()
                log.info("Database connection re-established")

            except Exception as e:
                log.error("Unexpected error processing event: %s", e, exc_info=True)
                await consumer.commit()

    except asyncio.CancelledError:
        log.info("IoT Consumer shutting down gracefully.")
    finally:
        await consumer.stop()
        conn.close()
        log.info("IoT Consumer stopped. Total events processed: %d", events_processed)


def main():
    log.info("=" * 60)
    log.info("FORTRESS IoT CONSUMER DAEMON — Event Log Writer")
    log.info("=" * 60)
    asyncio.run(consume())


if __name__ == "__main__":
    main()
