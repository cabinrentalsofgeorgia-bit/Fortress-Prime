"""
VRS Domain — Automation entities, schemas, allowed-value sets, and condition
operators.

This is the single source of truth for rule engine domain types.  Every layer
(infrastructure, application, presentation) imports from here.

Contains both the SQLAlchemy ORM models (VRSRuleEngine, AutomationEvent) and
the Pydantic event DTO (StreamlineEventPayload) so the bounded context owns
its own entities without leaking into generic model directories.
"""
from datetime import datetime
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, ForeignKey, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.core.database import Base

# ---------------------------------------------------------------------------
# Allowed-value sets
# ---------------------------------------------------------------------------

ALLOWED_ENTITIES = {"reservation", "work_order", "guest", "message"}
ALLOWED_TRIGGERS = {"created", "updated", "status_changed"}
ALLOWED_ACTIONS = {"send_email_template", "create_task", "notify_staff"}

# ---------------------------------------------------------------------------
# Condition operators
# ---------------------------------------------------------------------------

CMP_OPS: Dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: float(a) > float(b) if a is not None and b is not None else False,
    "lt": lambda a, b: float(a) < float(b) if a is not None and b is not None else False,
    "gte": lambda a, b: float(a) >= float(b) if a is not None and b is not None else False,
    "lte": lambda a, b: float(a) <= float(b) if a is not None and b is not None else False,
    "contains": lambda a, b: str(b) in str(a) if a is not None else False,
}

# ---------------------------------------------------------------------------
# SQLAlchemy ORM Entities
# ---------------------------------------------------------------------------


class VRSRuleEngine(Base):
    """Configurable event-driven automation rule."""
    __tablename__ = "vrs_automations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, index=True)
    target_entity = Column(String(50), nullable=False, index=True)
    trigger_event = Column(String(50), nullable=False, index=True)
    conditions = Column(JSONB, nullable=False, default=dict, server_default="{}")
    action_type = Column(String(50), nullable=False)
    action_payload = Column(JSONB, nullable=False, default=dict, server_default="{}")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<VRSRuleEngine {self.name!r} entity={self.target_entity!r} trigger={self.trigger_event!r}>"


class AutomationEvent(Base):
    """Audit trail for rule engine events — every entity change and rule execution."""
    __tablename__ = "vrs_automation_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vrs_automations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    previous_state = Column(JSONB, nullable=False, default=dict, server_default="{}")
    current_state = Column(JSONB, nullable=False, default=dict, server_default="{}")
    action_result = Column(String(20), nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AutomationEvent {self.entity_type}/{self.entity_id} {self.event_type} result={self.action_result}>"

# ---------------------------------------------------------------------------
# Pydantic Event DTO
# ---------------------------------------------------------------------------


class StreamlineEventPayload(BaseModel):
    """Canonical event DTO emitted by the sync loop and consumed by the rule engine."""
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    entity_id: str
    event_type: str
    previous_state: dict
    current_state: dict
