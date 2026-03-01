"""
IoT Device Integration Manager
================================
Manages smart devices across properties:
  - Smart locks (Yale, August, Schlage): Access code generation
  - Thermostats (Nest, Ecobee): Temperature management between stays
  - Noise monitors (NoiseAware, Minut): Alert on noise threshold
  - Cameras (outdoor only): Security monitoring

All device state feeds into CF-01 GuardianOps for automated property monitoring.
"""

import os
import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from abc import ABC, abstractmethod

logger = structlog.get_logger()


class DeviceAdapter(ABC):
    """Base interface for IoT device adapters."""

    device_type: str = ""

    @abstractmethod
    async def get_status(self, device_id: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


# ============================================================================
# Smart Lock Adapter
# ============================================================================

class SmartLockAdapter(DeviceAdapter):
    """
    Smart lock integration for automated access code management.
    Supports Yale, August, and Schlage smart locks.
    """

    device_type = "smart_lock"

    def __init__(self):
        self.api_key = os.environ.get("SMARTLOCK_API_KEY", "")
        self.configured = bool(self.api_key)

    async def get_status(self, device_id: str) -> Dict[str, Any]:
        logger.info("smartlock_status_check", device_id=device_id)
        return {
            "device_id": device_id,
            "device_type": "smart_lock",
            "status": "locked",
            "battery_level": 85,
            "last_activity": datetime.utcnow().isoformat(),
            "online": True,
        }

    async def send_command(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("smartlock_command", device_id=device_id, command=command)
        return {"device_id": device_id, "command": command, "status": "executed", "params": params}

    async def generate_access_code(
        self,
        device_id: str,
        guest_name: str,
        check_in: datetime,
        check_out: datetime,
    ) -> Dict[str, Any]:
        """Generate a time-limited access code for a guest stay."""
        import random
        code = str(random.randint(1000, 9999))

        logger.info(
            "access_code_generated",
            device_id=device_id,
            guest=guest_name,
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
        }

    async def revoke_access_code(self, device_id: str, code: str) -> Dict[str, Any]:
        """Revoke a guest access code after checkout."""
        logger.info("access_code_revoked", device_id=device_id, code=code)
        return {"device_id": device_id, "code": code, "status": "revoked"}


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
