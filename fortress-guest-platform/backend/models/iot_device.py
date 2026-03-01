"""
Digital Twin ORM Models — IoT device state persisted from the Z-Wave mesh.

Tables live in the ``iot_schema`` PostgreSQL schema, created by
``database/migrations/004_digital_twins.sql``.

Read path:  FGP API (``backend/api/iot.py``) queries these via async SQLAlchemy.
Write path: Standalone ``src/digital_twin_manager.py`` UPSERTs via raw SQL.
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------

class DigitalTwin(Base):
    """One row per physical IoT device across all properties."""

    __tablename__ = "digital_twins"
    __table_args__ = {"schema": "iot_schema"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), unique=True, nullable=False, index=True)
    property_id = Column(String(100), nullable=False, default="unassigned", index=True)
    device_type = Column(String(50), nullable=False)
    device_name = Column(String(255))
    state_json = Column(JSONB, nullable=False, server_default="{}")
    battery_level = Column(Integer, default=100)
    is_online = Column(Boolean, default=True)
    last_event_ts = Column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeviceEvent(Base):
    """Bounded audit log of state-change events per device."""

    __tablename__ = "device_events"
    __table_args__ = {"schema": "iot_schema"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class DigitalTwinResponse(BaseModel):
    id: str
    device_id: str
    property_id: str
    device_type: str
    device_name: str | None = None
    state_json: dict = Field(default_factory=dict)
    battery_level: int | None = 100
    is_online: bool = True
    last_event_ts: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DeviceEventResponse(BaseModel):
    id: str
    device_id: str
    event_type: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TwinSummaryResponse(BaseModel):
    total_devices: int = 0
    online_count: int = 0
    offline_count: int = 0
    low_battery_count: int = 0
    device_types: dict = Field(default_factory=dict)
