"""
VRS Automations API — CRUD for automation rules, event audit trail, and
supporting lookups (email templates for action payload UI).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.vrs.domain.automations import (
    VRSRuleEngine,
    AutomationEvent,
    StreamlineEventPayload,
    ALLOWED_ENTITIES,
    ALLOWED_TRIGGERS,
    ALLOWED_ACTIONS,
)
from backend.vrs.application.rule_engine import RuleEngine

logger = structlog.get_logger(service="vrs_automations_api")

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class RuleCondition(BaseModel):
    field: str
    operator: str
    value: Union[str, int, float]


class RuleConditionsGroup(BaseModel):
    operator: str = "AND"
    rules: List[RuleCondition] = Field(default_factory=list)


class RuleResponse(BaseModel):
    id: UUID
    name: str
    target_entity: str
    trigger_event: str
    conditions: Dict[str, Any]
    action_type: str
    action_payload: Dict[str, Any]
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    target_entity: str = Field(..., min_length=1, max_length=50)
    trigger_event: str = Field(..., min_length=1, max_length=50)
    conditions: RuleConditionsGroup = Field(default_factory=RuleConditionsGroup)
    action_type: str = Field(..., min_length=1, max_length=50)
    action_payload: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class RuleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    target_entity: Optional[str] = Field(None, max_length=50)
    trigger_event: Optional[str] = Field(None, max_length=50)
    conditions: Optional[RuleConditionsGroup] = None
    action_type: Optional[str] = Field(None, max_length=50)
    action_payload: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class EventResponse(BaseModel):
    id: UUID
    rule_id: Optional[UUID] = None
    entity_type: str
    entity_id: str
    event_type: str
    previous_state: Dict[str, Any]
    current_state: Dict[str, Any]
    action_result: Optional[str] = None
    error_detail: Optional[str] = None
    created_at: Optional[datetime] = None


class DryRunRequest(BaseModel):
    entity_type: str
    entity_id: str = "test-entity-001"
    event_type: str
    previous_state: Dict[str, Any] = Field(default_factory=dict)
    current_state: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule_to_response(r: VRSRuleEngine) -> RuleResponse:
    return RuleResponse(
        id=r.id,
        name=r.name,
        target_entity=r.target_entity,
        trigger_event=r.trigger_event,
        conditions=r.conditions or {},
        action_type=r.action_type,
        action_payload=r.action_payload or {},
        is_active=r.is_active,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _event_to_response(e: AutomationEvent) -> EventResponse:
    return EventResponse(
        id=e.id,
        rule_id=e.rule_id,
        entity_type=e.entity_type,
        entity_id=e.entity_id,
        event_type=e.event_type,
        previous_state=e.previous_state or {},
        current_state=e.current_state or {},
        action_result=e.action_result,
        error_detail=e.error_detail,
        created_at=e.created_at,
    )


def _validate_enum(value: str, allowed: set, field_name: str):
    if value not in allowed:
        raise HTTPException(
            422,
            f"Invalid {field_name}: '{value}'. Allowed: {sorted(allowed)}",
        )


# ---------------------------------------------------------------------------
# CRUD Endpoints — static paths MUST be defined before /{rule_id} so
# FastAPI does not match "/events" or "/queue-status" as a UUID parameter.
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[RuleResponse])
async def list_rules(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(VRSRuleEngine).order_by(VRSRuleEngine.name)
    if active_only:
        stmt = stmt.where(VRSRuleEngine.is_active == True)
    result = await db.execute(stmt)
    return [_rule_to_response(r) for r in result.scalars().all()]


@router.post("/", response_model=RuleResponse, status_code=201)
async def create_rule(
    body: RuleCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    _validate_enum(body.target_entity, ALLOWED_ENTITIES, "target_entity")
    _validate_enum(body.trigger_event, ALLOWED_TRIGGERS, "trigger_event")
    _validate_enum(body.action_type, ALLOWED_ACTIONS, "action_type")

    rule = VRSRuleEngine(
        name=body.name,
        target_entity=body.target_entity,
        trigger_event=body.trigger_event,
        conditions=body.conditions.model_dump(),
        action_type=body.action_type,
        action_payload=body.action_payload,
        is_active=body.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    logger.info("rule_created", rule_id=str(rule.id), name=rule.name)
    return _rule_to_response(rule)


# ---------------------------------------------------------------------------
# Event Audit Trail (before /{rule_id} to avoid path-param collision)
# ---------------------------------------------------------------------------

@router.get("/events", response_model=List[EventResponse])
async def list_events(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AutomationEvent)
        .order_by(desc(AutomationEvent.created_at))
        .offset(offset)
        .limit(limit)
    )
    return [_event_to_response(e) for e in result.scalars().all()]


@router.get("/events/{rule_id}", response_model=List[EventResponse])
async def list_rule_events(
    rule_id: UUID,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AutomationEvent)
        .where(AutomationEvent.rule_id == rule_id)
        .order_by(desc(AutomationEvent.created_at))
        .limit(limit)
    )
    return [_event_to_response(e) for e in result.scalars().all()]


# ---------------------------------------------------------------------------
# Queue Status (before /{rule_id})
# ---------------------------------------------------------------------------

@router.get("/queue-status")
async def queue_status():
    """Return the current depth of the Redis event queue."""
    from backend.vrs.infrastructure.event_bus import queue_depth
    depth = await queue_depth()
    return {"queue_key": "fortress:events:streamline", "depth": depth}


# ---------------------------------------------------------------------------
# Supporting Lookups (before /{rule_id})
# ---------------------------------------------------------------------------

class EmailTemplateSummary(BaseModel):
    id: UUID
    name: str
    subject_template: str


@router.get("/email-templates", response_model=List[EmailTemplateSummary])
async def list_email_templates(db: AsyncSession = Depends(get_db)):
    """Returns active email templates for the send_email_template action dropdown."""
    from backend.models.template import EmailTemplate

    result = await db.execute(
        select(
            EmailTemplate.id,
            EmailTemplate.name,
            EmailTemplate.subject_template,
        )
        .where(EmailTemplate.is_active == True)
        .order_by(EmailTemplate.name)
    )
    return [
        EmailTemplateSummary(id=row.id, name=row.name, subject_template=row.subject_template)
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# Single-rule CRUD (dynamic /{rule_id} MUST come after all static paths)
# ---------------------------------------------------------------------------

@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VRSRuleEngine).where(VRSRuleEngine.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return _rule_to_response(rule)


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: UUID,
    body: RuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(VRSRuleEngine).where(VRSRuleEngine.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    if body.target_entity is not None:
        _validate_enum(body.target_entity, ALLOWED_ENTITIES, "target_entity")
        rule.target_entity = body.target_entity
    if body.trigger_event is not None:
        _validate_enum(body.trigger_event, ALLOWED_TRIGGERS, "trigger_event")
        rule.trigger_event = body.trigger_event
    if body.action_type is not None:
        _validate_enum(body.action_type, ALLOWED_ACTIONS, "action_type")
        rule.action_type = body.action_type
    if body.name is not None:
        rule.name = body.name
    if body.conditions is not None:
        rule.conditions = body.conditions.model_dump()
    if body.action_payload is not None:
        rule.action_payload = body.action_payload
    if body.is_active is not None:
        rule.is_active = body.is_active

    rule.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(rule)
    logger.info("rule_updated", rule_id=str(rule.id), name=rule.name)
    return _rule_to_response(rule)


@router.delete("/{rule_id}", response_model=RuleResponse)
async def deactivate_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VRSRuleEngine).where(VRSRuleEngine.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    rule.is_active = False
    rule.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(rule)
    logger.info("rule_deactivated", rule_id=str(rule.id), name=rule.name)
    return _rule_to_response(rule)


# ---------------------------------------------------------------------------
# Dry-Run Test
# ---------------------------------------------------------------------------

@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: UUID,
    body: DryRunRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(VRSRuleEngine).where(VRSRuleEngine.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    event = StreamlineEventPayload(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        event_type=body.event_type,
        previous_state=body.previous_state,
        current_state=body.current_state,
    )
    dry_result = RuleEngine.evaluate_dry_run(rule.conditions, event)
    return {
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        **dry_result,
    }
