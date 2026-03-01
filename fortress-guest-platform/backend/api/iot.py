"""
IoT Device Management API — Digital Twin queries + device lifecycle actions.

Read path queries the local ``iot_schema.digital_twins`` table (zero-latency).
Write path delegates to the adapter layer for physical device commands.
"""

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.integrations.iot_manager import IoTManager
from backend.models.iot_device import (
    DeviceEvent,
    DeviceEventResponse,
    DigitalTwin,
    DigitalTwinResponse,
    TwinSummaryResponse,
)
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter()
iot = IoTManager()


# ---------------------------------------------------------------------------
# Pydantic request models (existing + new)
# ---------------------------------------------------------------------------

class DeviceStatusRequest(BaseModel):
    device_id: str
    device_type: str


class PrepareArrivalRequest(BaseModel):
    property_id: str
    guest_name: str
    check_in: str
    check_out: str
    lock_device_id: Optional[str] = None
    thermostat_device_id: Optional[str] = None


class ProcessCheckoutRequest(BaseModel):
    property_id: str
    access_code: Optional[str] = None
    lock_device_id: Optional[str] = None
    thermostat_device_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Digital Twin read endpoints (zero-latency Postgres queries)
# ---------------------------------------------------------------------------

@router.get("/twins", response_model=List[DigitalTwinResponse])
async def list_all_twins(
    db: AsyncSession = Depends(get_db),
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all digital twins across the entire property portfolio."""
    stmt = select(DigitalTwin).order_by(DigitalTwin.updated_at.desc())

    if device_type:
        stmt = stmt.where(DigitalTwin.device_type == device_type)

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    twins = result.scalars().all()

    return [_twin_to_response(t) for t in twins]


@router.get("/twins/summary", response_model=TwinSummaryResponse)
async def twin_summary(db: AsyncSession = Depends(get_db)):
    """Dashboard KPI summary: counts, online status, battery alerts."""
    total_q = await db.execute(select(func.count(DigitalTwin.id)))
    total = total_q.scalar() or 0

    online_q = await db.execute(
        select(func.count(DigitalTwin.id)).where(DigitalTwin.is_online.is_(True))
    )
    online = online_q.scalar() or 0

    low_batt_q = await db.execute(
        select(func.count(DigitalTwin.id)).where(DigitalTwin.battery_level < 20)
    )
    low_battery = low_batt_q.scalar() or 0

    type_q = await db.execute(
        select(DigitalTwin.device_type, func.count(DigitalTwin.id))
        .group_by(DigitalTwin.device_type)
    )
    device_types = {row[0]: row[1] for row in type_q.all()}

    return TwinSummaryResponse(
        total_devices=total,
        online_count=online,
        offline_count=total - online,
        low_battery_count=low_battery,
        device_types=device_types,
    )


@router.get("/twins/{property_id}", response_model=List[DigitalTwinResponse])
async def get_property_twins(property_id: str, db: AsyncSession = Depends(get_db)):
    """All digital twins for a specific property."""
    result = await db.execute(
        select(DigitalTwin)
        .where(DigitalTwin.property_id == property_id)
        .order_by(DigitalTwin.device_type)
    )
    twins = result.scalars().all()
    if not twins:
        return []
    return [_twin_to_response(t) for t in twins]


@router.get("/twins/{property_id}/{device_id}", response_model=DigitalTwinResponse)
async def get_single_twin(property_id: str, device_id: str, db: AsyncSession = Depends(get_db)):
    """Single device detail with its current twin state."""
    result = await db.execute(
        select(DigitalTwin).where(
            DigitalTwin.device_id == device_id,
            DigitalTwin.property_id == property_id,
        )
    )
    twin = result.scalar_one_or_none()
    if not twin:
        raise HTTPException(status_code=404, detail="Digital Twin not found")
    return _twin_to_response(twin)


@router.get("/events/{device_id}", response_model=List[DeviceEventResponse])
async def get_device_events(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Recent state-change events for a device (audit log)."""
    result = await db.execute(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device_id)
        .order_by(DeviceEvent.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        DeviceEventResponse(
            id=str(e.id),
            device_id=e.device_id,
            event_type=e.event_type,
            payload=e.payload or {},
            created_at=e.created_at,
        )
        for e in events
    ]


# ---------------------------------------------------------------------------
# Legacy device-command endpoints (adapter layer — physical hardware)
# ---------------------------------------------------------------------------

@router.post("/device-status")
async def get_device_status(body: DeviceStatusRequest):
    """Get the current status of an IoT device via its adapter."""
    adapter_map = {
        "smart_lock": iot.locks,
        "thermostat": iot.thermostats,
        "noise_monitor": iot.noise,
    }
    adapter = adapter_map.get(body.device_type)
    if not adapter:
        return {"error": f"Unknown device type: {body.device_type}"}
    return await adapter.get_status(body.device_id)


@router.post("/prepare-arrival")
async def prepare_arrival(body: PrepareArrivalRequest):
    """Prepare all IoT devices for a guest arrival."""
    return await iot.prepare_for_arrival(
        property_id=body.property_id,
        guest_name=body.guest_name,
        check_in=datetime.fromisoformat(body.check_in),
        check_out=datetime.fromisoformat(body.check_out),
        lock_device_id=body.lock_device_id,
        thermostat_device_id=body.thermostat_device_id,
    )


@router.post("/process-checkout")
async def process_checkout(body: ProcessCheckoutRequest):
    """Reset IoT devices after guest checkout."""
    return await iot.process_checkout(
        property_id=body.property_id,
        access_code=body.access_code,
        lock_device_id=body.lock_device_id,
        thermostat_device_id=body.thermostat_device_id,
    )


@router.get("/devices/{property_id}")
async def list_property_devices(property_id: str, db: AsyncSession = Depends(get_db)):
    """List all IoT devices for a property (queries the digital twin table)."""
    result = await db.execute(
        select(DigitalTwin).where(DigitalTwin.property_id == property_id)
    )
    twins = result.scalars().all()
    return {
        "property_id": property_id,
        "devices": [_twin_to_response(t) for t in twins],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _twin_to_response(t: DigitalTwin) -> DigitalTwinResponse:
    return DigitalTwinResponse(
        id=str(t.id),
        device_id=t.device_id,
        property_id=t.property_id,
        device_type=t.device_type,
        device_name=t.device_name,
        state_json=t.state_json or {},
        battery_level=t.battery_level,
        is_online=t.is_online if t.is_online is not None else True,
        last_event_ts=t.last_event_ts,
        updated_at=t.updated_at,
    )
