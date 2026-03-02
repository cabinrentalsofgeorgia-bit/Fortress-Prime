"""
Fortress Z-Wave IoT Bridge — MQTT-to-Redpanda Event Translator

Connects to a local Z-Wave hub's MQTT broker (Z-Wave JS UI or Hubitat),
translates raw device messages into enterprise events, and publishes them
to the Redpanda event bus.

Modes:
    live      — Listens to a real MQTT broker on the LAN.
    simulate  — Generates mock device events for end-to-end pipeline testing.

Usage:
    IOT_BRIDGE_MODE=simulate python -m src.iot_zwave_bridge
    IOT_BRIDGE_MODE=live     python -m src.iot_zwave_bridge
"""

import asyncio
import json
import logging
import os
import random
import signal
from datetime import datetime, timezone

from src.event_publisher import EventPublisher, close_event_publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("iot_zwave_bridge")

# ---------------------------------------------------------------------------
# Configuration (sourced from env / config.py)
# ---------------------------------------------------------------------------
BRIDGE_MODE = os.getenv("IOT_BRIDGE_MODE", "simulate")
MQTT_BROKER = os.getenv("MQTT_BROKER_URL", "192.168.0.50")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
SIMULATE_INTERVAL = int(os.getenv("IOT_SIMULATE_INTERVAL", "30"))

MOCK_DEVICES = [
    {"device_id": "FrontDoorLock_CabinA", "property_id": "cabin_a", "device_type": "smart_lock"},
    {"device_id": "BackDoorLock_CabinA",  "property_id": "cabin_a", "device_type": "smart_lock"},
    {"device_id": "FrontDoorLock_CabinB", "property_id": "cabin_b", "device_type": "smart_lock"},
    {"device_id": "Thermostat_CabinA",    "property_id": "cabin_a", "device_type": "thermostat"},
    {"device_id": "Thermostat_CabinB",    "property_id": "cabin_b", "device_type": "thermostat"},
]


# ---------------------------------------------------------------------------
# Event publishing helpers
# ---------------------------------------------------------------------------

async def publish_lock_event(device_id: str, state: str, raw_value: int, user_code: str = None):
    """Publish a normalized lock state change to Redpanda."""
    payload = {
        "device_id": device_id,
        "device_type": "smart_lock",
        "state": state,
        "raw_zwave_value": raw_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if user_code is not None:
        payload["user_code"] = str(user_code)
    await EventPublisher.publish(
        topic="iot.locks.state_changed",
        payload=payload,
        key=device_id,
    )
    code_info = f" (code={user_code})" if user_code else ""
    log.info("[Z-WAVE BRIDGE] Lock event -> Redpanda: %s is %s%s", device_id, state, code_info)


async def publish_thermostat_event(device_id: str, temperature: float):
    """Publish a thermostat reading to Redpanda."""
    payload = {
        "device_id": device_id,
        "device_type": "thermostat",
        "state": "active",
        "temperature": temperature,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await EventPublisher.publish(
        topic="iot.thermostat.state_changed",
        payload=payload,
        key=device_id,
    )
    log.info("[Z-WAVE BRIDGE] Thermostat event -> Redpanda: %s at %.1f°F", device_id, temperature)


async def publish_battery_event(device_id: str, battery: int):
    """Route battery alerts to the system health stream."""
    payload = {
        "type": "iot_battery_update",
        "data": {
            "device_id": device_id,
            "battery": battery,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    await EventPublisher.publish(
        topic="system.health.alerts",
        payload=payload,
        key=device_id,
    )
    log.info("[Z-WAVE BRIDGE] Battery event -> Redpanda: %s at %d%%", device_id, battery)


# ---------------------------------------------------------------------------
# Live MQTT mode
# ---------------------------------------------------------------------------

def _extract_user_code(data: dict) -> str | None:
    """
    Extract the user code / slot ID from a Z-Wave lock MQTT payload.

    Yale Assure (and compatible locks) report user codes via:
      - Z-Wave Alarm CC (notification type 0x06): "userId" or "user_id" field
      - Z-Wave Entry Control CC: "userCode" field
      - Z-Wave JS UI enriched payloads: "event.userId" or "parameters.userId"
    """
    for key in ("userId", "user_id", "userCode", "user_code"):
        val = data.get(key)
        if val is not None:
            return str(val)

    if isinstance(data.get("event"), dict):
        for key in ("userId", "userCode"):
            val = data["event"].get(key)
            if val is not None:
                return str(val)

    if isinstance(data.get("parameters"), dict):
        for key in ("userId", "userCode"):
            val = data["parameters"].get(key)
            if val is not None:
                return str(val)

    return None


async def translate_mqtt_message(topic: str, raw_payload: str):
    """Translate a raw Z-Wave MQTT message into a Redpanda enterprise event."""
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        log.warning("Non-JSON payload on topic %s, skipping", topic)
        return

    parts = topic.split("/")
    if len(parts) < 2:
        return

    device_id = parts[1]

    if "Door_state" in topic or "currentValue" in topic or "Access_Control" in topic or "notification" in topic:
        state = "locked" if data.get("value") == 255 else "unlocked"
        user_code = _extract_user_code(data)
        await publish_lock_event(device_id, state, data.get("value", 0), user_code)

    elif "Battery_level" in topic:
        await publish_battery_event(device_id, data.get("value", 100))

    elif "Air_temperature" in topic:
        await publish_thermostat_event(device_id, data.get("value", 0))


async def run_live_bridge():
    """Maintain a persistent async connection to the local Z-Wave MQTT broker."""
    import aiomqtt  # deferred import — only needed in live mode

    log.info("Connecting to Z-Wave MQTT Broker at %s:%d ...", MQTT_BROKER, MQTT_PORT)
    reconnect_delay = 5

    while True:
        try:
            async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
                log.info("Connected to Z-Wave Broker. Subscribing to zwave/#")
                await client.subscribe("zwave/#")

                async for message in client.messages:
                    topic = message.topic.value
                    payload = message.payload.decode()
                    await translate_mqtt_message(topic, payload)

        except aiomqtt.MqttError as err:
            log.warning("MQTT connection lost: %s. Reconnecting in %ds...", err, reconnect_delay)
            await asyncio.sleep(reconnect_delay)
        except asyncio.CancelledError:
            log.info("Z-Wave Bridge live mode shutting down.")
            break


# ---------------------------------------------------------------------------
# Simulation mode
# ---------------------------------------------------------------------------

async def run_simulation():
    """Generate realistic mock events for pipeline testing."""
    log.info(
        "SIMULATION MODE active. Generating mock events every %ds for %d devices.",
        SIMULATE_INTERVAL,
        len(MOCK_DEVICES),
    )

    while True:
        try:
            device = random.choice(MOCK_DEVICES)
            did = device["device_id"]
            dtype = device["device_type"]

            if dtype == "smart_lock":
                is_locked = random.choice([True, False])
                state = "locked" if is_locked else "unlocked"
                raw_val = 255 if is_locked else 0
                await publish_lock_event(did, state, raw_val)

                if random.random() < 0.3:
                    battery = random.randint(15, 100)
                    await publish_battery_event(did, battery)

            elif dtype == "thermostat":
                temp = round(random.uniform(62.0, 78.0), 1)
                await publish_thermostat_event(did, temp)

            await asyncio.sleep(random.randint(SIMULATE_INTERVAL // 2, SIMULATE_INTERVAL * 2))
        except asyncio.CancelledError:
            log.info("Simulation mode shutting down.")
            break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown()))

    if BRIDGE_MODE == "live":
        await run_live_bridge()
    else:
        await run_simulation()


async def _shutdown():
    log.info("Graceful shutdown requested.")
    await close_event_publisher()
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Z-Wave Bridge.")
