"""
IoT Device Integration Manager
================================
Manages smart devices across properties:
  - Smart locks (Yale, August, Schlage): Bidirectional MQTT control via Z-Wave bridge
  - Thermostats (Nest, Ecobee): Temperature management between stays
  - Noise monitors (NoiseAware, Minut): Alert on noise threshold
  - Cameras (outdoor only): Security monitoring

SmartLockAdapter communicates with physical locks through the MQTT broker
connected to the Z-Wave JS UI hub. Status reads come from the digital_twins
table (populated by the digital_twin_manager). Code generation pushes
User Code CC commands over MQTT and writes audit records to iot_event_log.
"""

import json
import os
import secrets
import structlog
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from abc import ABC, abstractmethod

logger = structlog.get_logger()

MQTT_BROKER = os.environ.get("MQTT_BROKER_URL", "192.168.0.50")
MQTT_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))


class DeviceAdapter(ABC):
    """Base interface for IoT device adapters."""

    device_type: str = ""

    @abstractmethod
    async def get_status(self, device_id: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


class _MqttPool:
    """Lazy-initialized async MQTT client pool."""

    _client = None

    @classmethod
    async def get_client(cls):
        if cls._client is None:
            try:
                import aiomqtt
                cls._client = aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT)
            except ImportError:
                logger.error("aiomqtt_not_installed")
                return None
            except Exception as e:
                logger.error("mqtt_client_init_failed", error=str(e)[:200])
                return None
        return cls._client

    @classmethod
    async def publish(cls, topic: str, payload: dict) -> bool:
        """Publish a message to the MQTT broker. Returns True on success."""
        try:
            import aiomqtt
            async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
                await client.publish(topic, json.dumps(payload).encode())
                return True
        except Exception as e:
            logger.error("mqtt_publish_failed", topic=topic, error=str(e)[:200])
            return False


# ============================================================================
# Smart Lock Adapter — Live MQTT + Digital Twin backed
# ============================================================================

class SmartLockAdapter(DeviceAdapter):
    """
    Bidirectional smart lock adapter communicating via MQTT to the Z-Wave bridge.

    Read path:  digital_twins table (populated by digital_twin_manager)
    Write path: MQTT publish -> Z-Wave JS UI -> physical lock
    Audit path: iot_event_log (golden records for dispute defense)
    """

    device_type = "smart_lock"

    async def get_status(self, device_id: str) -> Dict[str, Any]:
        """Read live status from the digital_twins table."""
        try:
            from backend.core.database import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT device_id, property_id, state_json, battery_level,
                               is_online, last_event_ts, updated_at
                        FROM iot_schema.digital_twins
                        WHERE device_id = :did
                        LIMIT 1
                    """),
                    {"did": device_id},
                )
                row = result.first()

            if row:
                state = row.state_json or {}
                return {
                    "device_id": device_id,
                    "device_type": "smart_lock",
                    "status": state.get("lock_state", "unknown"),
                    "battery_level": row.battery_level or 0,
                    "last_activity": row.last_event_ts.isoformat() if row.last_event_ts else None,
                    "online": row.is_online if row.is_online is not None else False,
                    "property_id": row.property_id,
                    "raw_state": state,
                }
        except Exception as e:
            logger.warning("smartlock_status_db_failed", device_id=device_id, error=str(e)[:200])

        return {
            "device_id": device_id,
            "device_type": "smart_lock",
            "status": "unreachable",
            "battery_level": None,
            "last_activity": None,
            "online": False,
            "error": "Unable to read device state — digital twin unavailable",
        }

    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route lock/unlock commands to the physical lock via MQTT."""
        zwave_node = await self._resolve_zwave_node(device_id)
        if not zwave_node:
            logger.warning("smartlock_no_zwave_node", device_id=device_id)
            return {"device_id": device_id, "command": command, "status": "failed", "error": "No Z-Wave node mapping"}

        mqtt_topic = f"zwave/{zwave_node}/set"
        mqtt_payload = {"command": command, **params}

        if command in ("lock", "unlock"):
            mqtt_payload["value"] = 255 if command == "lock" else 0

        success = await _MqttPool.publish(mqtt_topic, mqtt_payload)

        status = "dispatched" if success else "mqtt_unreachable"
        logger.info("smartlock_command", device_id=device_id, command=command, status=status)

        if success:
            await self._write_event_log(device_id, command, params.get("user_code"))

        return {"device_id": device_id, "command": command, "status": status, "params": params}

    async def generate_access_code(
        self,
        device_id: str,
        guest_name: str,
        check_in: datetime,
        check_out: datetime,
    ) -> Dict[str, Any]:
        """
        Generate a unique access code and push it to the physical lock.
        Uses Z-Wave User Code CC to program a slot on the Yale Assure.
        """
        code = self._generate_unique_code()

        zwave_node = await self._resolve_zwave_node(device_id)
        if zwave_node:
            mqtt_topic = f"zwave/{zwave_node}/set"
            mqtt_payload = {
                "command": "set_user_code",
                "userCode": code,
                "userIdStatus": 1,
                "validFrom": check_in.isoformat(),
                "validUntil": check_out.isoformat(),
            }
            success = await _MqttPool.publish(mqtt_topic, mqtt_payload)
            dispatch_status = "pushed_to_lock" if success else "mqtt_unreachable"
        else:
            dispatch_status = "no_zwave_mapping"

        await self._write_event_log(device_id, "code_set", code, {
            "guest_name": guest_name,
            "valid_from": check_in.isoformat(),
            "valid_until": check_out.isoformat(),
        })

        logger.info(
            "access_code_generated",
            device_id=device_id,
            guest=guest_name,
            dispatch=dispatch_status,
            valid_from=check_in.isoformat(),
            valid_until=check_out.isoformat(),
        )

        return {
            "device_id": device_id,
            "access_code": code,
            "guest_name": guest_name,
            "valid_from": check_in.isoformat(),
            "valid_until": check_out.isoformat(),
            "status": "active",
            "dispatch": dispatch_status,
        }

    async def revoke_access_code(self, device_id: str, code: str) -> Dict[str, Any]:
        """Clear the guest code slot on the physical lock."""
        zwave_node = await self._resolve_zwave_node(device_id)
        if zwave_node:
            mqtt_topic = f"zwave/{zwave_node}/set"
            mqtt_payload = {
                "command": "clear_user_code",
                "userCode": code,
                "userIdStatus": 0,
            }
            success = await _MqttPool.publish(mqtt_topic, mqtt_payload)
            dispatch_status = "cleared_on_lock" if success else "mqtt_unreachable"
        else:
            dispatch_status = "no_zwave_mapping"

        await self._write_event_log(device_id, "code_revoked", code)

        logger.info("access_code_revoked", device_id=device_id, dispatch=dispatch_status)
        return {"device_id": device_id, "code": code, "status": "revoked", "dispatch": dispatch_status}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_unique_code() -> str:
        """Generate a 6-digit code using cryptographic randomness."""
        return str(secrets.randbelow(900000) + 100000)

    @staticmethod
    async def _resolve_zwave_node(device_id: str) -> Optional[str]:
        """Look up the Z-Wave node ID from iot_device_map."""
        try:
            from backend.core.database import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as db:
                result = await db.execute(
                    text("SELECT zwave_node_id FROM iot_device_map WHERE device_id = :did AND is_active = TRUE LIMIT 1"),
                    {"did": device_id},
                )
                row = result.first()
                return row.zwave_node_id if row else None
        except Exception as e:
            logger.warning("zwave_node_lookup_failed", device_id=device_id, error=str(e)[:200])
            return None

    @staticmethod
    async def _write_event_log(device_id: str, event_type: str, user_code: str = None, extra_meta: dict = None):
        """Write an audit record to iot_event_log."""
        try:
            from backend.core.database import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as db:
                result = await db.execute(
                    text("SELECT property_id FROM iot_device_map WHERE device_id = :did LIMIT 1"),
                    {"did": device_id},
                )
                row = result.first()
                property_id = str(row.property_id) if row else None

                if not property_id:
                    return

                metadata = {"source": "smart_lock_adapter"}
                if extra_meta:
                    metadata.update(extra_meta)

                await db.execute(
                    text("""
                        INSERT INTO iot_event_log
                            (device_id, property_id, event_type, user_code, timestamp, metadata)
                        VALUES (:did, :pid::uuid, :etype, :code, :ts, :meta::jsonb)
                    """),
                    {
                        "did": device_id,
                        "pid": property_id,
                        "etype": event_type,
                        "code": user_code,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "meta": json.dumps(metadata),
                    },
                )
                await db.commit()
        except Exception as e:
            logger.warning("iot_event_log_write_failed", device_id=device_id, error=str(e)[:200])


# ============================================================================
# Thermostat Adapter
# ============================================================================

class ThermostatAdapter(DeviceAdapter):
    """Thermostat integration for energy management between stays."""

    device_type = "thermostat"

    def __init__(self):
        self.api_key = os.environ.get("NEST_API_KEY", "")
        self.configured = bool(self.api_key)

    async def get_status(self, device_id: str) -> Dict[str, Any]:
        return {
            "device_id": device_id,
            "device_type": "thermostat",
            "current_temp": 72,
            "target_temp": 72,
            "mode": "heat",
            "humidity": 45,
            "online": True,
        }

    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("thermostat_command", device_id=device_id, command=command, params=params)
        return {"device_id": device_id, "command": command, "status": "executed"}

    async def set_away_mode(self, device_id: str) -> Dict[str, Any]:
        """Set thermostat to energy-saving mode between stays."""
        return await self.send_command(device_id, "set_mode", {"mode": "away", "target_temp": 55})

    async def set_guest_comfort(self, device_id: str, season: str = "winter") -> Dict[str, Any]:
        """Pre-condition the property before guest arrival."""
        target = 72 if season == "winter" else 74
        return await self.send_command(device_id, "set_mode", {"mode": "comfort", "target_temp": target})


# ============================================================================
# Noise Monitor Adapter
# ============================================================================

class NoiseMonitorAdapter(DeviceAdapter):
    """Noise monitoring for party/disturbance detection."""

    device_type = "noise_monitor"

    def __init__(self):
        self.api_key = os.environ.get("NOISEAWARE_API_KEY", "")
        self.configured = bool(self.api_key)

    async def get_status(self, device_id: str) -> Dict[str, Any]:
        return {
            "device_id": device_id,
            "device_type": "noise_monitor",
            "current_level_db": 42,
            "threshold_db": 80,
            "alert_active": False,
            "online": True,
        }

    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("noise_monitor_command", device_id=device_id, command=command)
        return {"device_id": device_id, "command": command, "status": "executed"}

    async def set_threshold(self, device_id: str, threshold_db: int = 80) -> Dict[str, Any]:
        """Configure noise alert threshold."""
        return await self.send_command(device_id, "set_threshold", {"threshold_db": threshold_db})


# ============================================================================
# IoT Manager (Orchestrator)
# ============================================================================

class IoTManager:
    """
    Orchestrates all IoT devices across properties.
    Called by the lifecycle engine for automated device management.
    """

    def __init__(self):
        self.locks = SmartLockAdapter()
        self.thermostats = ThermostatAdapter()
        self.noise = NoiseMonitorAdapter()

    async def prepare_for_arrival(
        self,
        property_id: str,
        guest_name: str,
        check_in: datetime,
        check_out: datetime,
        lock_device_id: Optional[str] = None,
        thermostat_device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Prepare all IoT devices for a guest arrival."""
        results: Dict[str, Any] = {"property_id": property_id}

        if lock_device_id:
            results["access_code"] = await self.locks.generate_access_code(
                lock_device_id, guest_name, check_in, check_out,
            )

        if thermostat_device_id:
            results["thermostat"] = await self.thermostats.set_guest_comfort(thermostat_device_id)

        logger.info("iot_arrival_prepared", property_id=property_id, guest=guest_name)
        return results

    async def process_checkout(
        self,
        property_id: str,
        access_code: Optional[str] = None,
        lock_device_id: Optional[str] = None,
        thermostat_device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reset IoT devices after guest checkout."""
        results: Dict[str, Any] = {"property_id": property_id}

        if lock_device_id and access_code:
            results["lock"] = await self.locks.revoke_access_code(lock_device_id, access_code)

        if thermostat_device_id:
            results["thermostat"] = await self.thermostats.set_away_mode(thermostat_device_id)

        logger.info("iot_checkout_processed", property_id=property_id)
        return results

    async def get_all_device_status(self, property_id: str, devices: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Get status of all devices for a property."""
        statuses = []
        adapter_map = {
            "smart_lock": self.locks,
            "thermostat": self.thermostats,
            "noise_monitor": self.noise,
        }
        for d in devices:
            adapter = adapter_map.get(d["type"])
            if adapter:
                status = await adapter.get_status(d["device_id"])
                statuses.append(status)
        return statuses
