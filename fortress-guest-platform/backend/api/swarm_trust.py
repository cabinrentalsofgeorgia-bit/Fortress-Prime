"""
Governance perimeter API for the GREC Agentic Trust Swarm.
"""
from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.agents.financial.grec_auditor import GRECAuditorAgent
from backend.agents.financial.streamline_oracle import StreamlineOracleAgent
from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.core.time import utc_now
from backend.models.staff import StaffRole, StaffUser
from backend.models.swarm_governance import (
    AgentRegistry,
    AgentRun,
    AgentRunStatus,
    Escalation,
    EscalationStatus,
    OperatorOverride,
    OverrideAction,
    TrustDecision,
    TrustDecisionStatus,
)
from backend.services.swarm_policy_engine import SwarmPolicyService

router = APIRouter()
policy_service = SwarmPolicyService()
swarm_view_access = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])
swarm_control_access = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])
STREAMLINE_ORACLE_AGENT_NAME = "StreamlineOracle"


class AgentRunDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=1, max_length=255)
    trigger_source: str = Field(min_length=1, max_length=100)
    proposed_payload: dict[str, Any] = Field(default_factory=dict)


class TrustDecisionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    proposed_payload: dict[str, Any]
    deterministic_score: float
    policy_evaluation: dict[str, Any]
    status: TrustDecisionStatus


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: UUID
    agent_name: str
    trigger_source: str
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    decisions: list[TrustDecisionSummaryResponse] = Field(default_factory=list)


class EscalationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    decision_id: UUID
    run_id: UUID
    agent_name: str
    reason_code: str
    status: EscalationStatus
    decision_status: TrustDecisionStatus
    proposed_payload: dict[str, Any]
    policy_evaluation: dict[str, Any]
    deterministic_score: float


class EscalationQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EscalationResponse]
    count: int


class OperatorOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_action: OverrideAction
    final_payload: dict[str, Any] = Field(default_factory=dict)


class OperatorOverrideResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    escalation_id: UUID
    decision_id: UUID
    operator_email: EmailStr
    override_action: OverrideAction
    final_payload: dict[str, Any]
    timestamp: datetime
    escalation_status: EscalationStatus
    decision_status: TrustDecisionStatus


class StreamlineWebhookTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    decision_id: UUID
    decision_status: TrustDecisionStatus
    policy_evaluation: dict[str, Any]


def _serialize_decision(decision: TrustDecision) -> TrustDecisionSummaryResponse:
    return TrustDecisionSummaryResponse(
        id=decision.id,
        proposed_payload=decision.proposed_payload,
        deterministic_score=decision.deterministic_score,
        policy_evaluation=decision.policy_evaluation,
        status=decision.status,
    )


def _serialize_run(run: AgentRun) -> AgentRunResponse:
    if run.agent is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Agent relation missing")
    return AgentRunResponse(
        id=run.id,
        agent_id=run.agent_id,
        agent_name=run.agent.name,
        trigger_source=run.trigger_source,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        decisions=[_serialize_decision(decision) for decision in run.decisions],
    )


def _serialize_escalation(escalation: Escalation) -> EscalationResponse:
    if escalation.decision is None or escalation.decision.run is None or escalation.decision.run.agent is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Escalation relations are incomplete",
        )
    decision = escalation.decision
    return EscalationResponse(
        id=escalation.id,
        decision_id=decision.id,
        run_id=decision.run_id,
        agent_name=decision.run.agent.name,
        reason_code=escalation.reason_code,
        status=escalation.status,
        decision_status=decision.status,
        proposed_payload=decision.proposed_payload,
        policy_evaluation=decision.policy_evaluation,
        deterministic_score=decision.deterministic_score,
    )


def _serialize_override(
    override: OperatorOverride,
    escalation: Escalation,
    decision: TrustDecision,
) -> OperatorOverrideResponse:
    return OperatorOverrideResponse(
        id=override.id,
        escalation_id=override.escalation_id,
        decision_id=decision.id,
        operator_email=override.operator_email,
        override_action=override.override_action,
        final_payload=override.final_payload,
        timestamp=override.timestamp,
        escalation_status=escalation.status,
        decision_status=decision.status,
    )


async def _get_agent_by_name(db: AsyncSession, agent_name: str) -> AgentRegistry | None:
    normalized_name = agent_name.strip()
    if not normalized_name:
        return None
    return (
        await db.execute(select(AgentRegistry).where(AgentRegistry.name == normalized_name))
    ).scalar_one_or_none()


async def _ensure_streamline_oracle_agent(db: AsyncSession) -> AgentRegistry:
    agent = await _get_agent_by_name(db, STREAMLINE_ORACLE_AGENT_NAME)
    if agent is not None:
        if not agent.is_active:
            agent.is_active = True
            await db.flush()
        return agent

    agent = AgentRegistry(
        name=STREAMLINE_ORACLE_AGENT_NAME,
        role="ingestion",
        is_active=True,
        scope_boundary={"allowed_accounts": ["all"]},
        daily_tool_budget=1000,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _create_agent_run(
    db: AsyncSession,
    *,
    agent: AgentRegistry,
    trigger_source: str,
) -> AgentRun:
    run = AgentRun(
        agent_id=agent.id,
        trigger_source=trigger_source.strip(),
        status=AgentRunStatus.RUNNING,
    )
    db.add(run)
    await db.flush()
    return run


async def _get_run_with_relations(db: AsyncSession, run_id: UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun)
            .options(
                selectinload(AgentRun.agent),
                selectinload(AgentRun.decisions),
            )
            .where(AgentRun.id == run_id)
        )
    ).scalar_one_or_none()


def _policy_reason_code(
    agent: AgentRegistry,
    is_authorized: bool,
    policy_evaluation: dict[str, Any],
) -> str:
    if not agent.is_active:
        return "agent_inactive"
    if not is_authorized:
        return "daily_tool_budget_exceeded"
    return str(policy_evaluation.get("reason_code") or "policy_violation")


async def _persist_run_decision(
    db: AsyncSession,
    *,
    run: AgentRun,
    agent: AgentRegistry,
    proposed_payload: dict[str, Any],
    policy_evaluation: dict[str, Any],
    decision_status: TrustDecisionStatus,
    deterministic_score: float,
) -> AgentRunResponse:
    decision = TrustDecision(
        run_id=run.id,
        proposed_payload=proposed_payload,
        deterministic_score=deterministic_score,
        policy_evaluation=policy_evaluation,
        status=decision_status,
    )
    db.add(decision)
    await db.flush()

    if decision_status == TrustDecisionStatus.AUTO_APPROVED:
        run.status = AgentRunStatus.COMPLETED
        run.completed_at = utc_now()
    else:
        run.status = AgentRunStatus.ESCALATED
        run.completed_at = utc_now()
        escalation = Escalation(
            decision_id=decision.id,
            reason_code=_policy_reason_code(
                agent,
                bool(policy_evaluation.get("agent_authorized")),
                policy_evaluation,
            ),
            status=EscalationStatus.PENDING,
        )
        db.add(escalation)

    await db.commit()

    run_with_relations = await _get_run_with_relations(db, run.id)
    if run_with_relations is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load created run")
    return _serialize_run(run_with_relations)


async def _mark_run_failed(
    db: AsyncSession,
    *,
    run: AgentRun,
) -> None:
    run.status = AgentRunStatus.FAILED
    run.completed_at = utc_now()
    await db.commit()


async def _dispatch_agent_run(
    db: AsyncSession,
    *,
    agent: AgentRegistry,
    trigger_source: str,
    proposed_payload: dict[str, Any],
) -> AgentRunResponse:
    is_authorized = await policy_service.evaluate_agent_authorization(db, agent.name)
    policy_evaluation = policy_service.evaluate_trust_decision(proposed_payload)
    policy_evaluation["agent_authorized"] = is_authorized
    compliant = bool(policy_evaluation.get("compliant")) and is_authorized
    policy_evaluation["compliant"] = compliant
    decision_status = (
        TrustDecisionStatus.AUTO_APPROVED if compliant else TrustDecisionStatus.ESCALATED
    )
    run = await _create_agent_run(
        db,
        agent=agent,
        trigger_source=trigger_source,
    )
    return await _persist_run_decision(
        db,
        run=run,
        agent=agent,
        proposed_payload=proposed_payload,
        policy_evaluation=policy_evaluation,
        decision_status=decision_status,
        deterministic_score=1.0 if compliant else 0.0,
    )


def _require_loopback_client(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    try:
        client_ip = ip_address(client_host)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Streamline test webhook is restricted to loopback clients.",
        ) from exc

    if not client_ip.is_loopback:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Streamline test webhook is restricted to loopback clients.",
        )


@router.post(
    "/dispatch",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_agent_run(
    body: AgentRunDispatchRequest,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(swarm_control_access),
) -> AgentRunResponse:
    agent = await _get_agent_by_name(db, body.agent_name)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return await _dispatch_agent_run(
        db,
        agent=agent,
        trigger_source=body.trigger_source,
        proposed_payload=body.proposed_payload,
    )


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(swarm_view_access),
) -> AgentRunResponse:
    run = await _get_run_with_relations(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _serialize_run(run)


@router.get("/escalations", response_model=EscalationQueueResponse)
async def list_escalations(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(swarm_view_access),
) -> EscalationQueueResponse:
    escalations = (
        await db.execute(
            select(Escalation)
            .join(Escalation.decision)
            .options(
                selectinload(Escalation.decision)
                .selectinload(TrustDecision.run)
                .selectinload(AgentRun.agent)
            )
            .where(
                Escalation.status == EscalationStatus.PENDING,
                TrustDecision.status == TrustDecisionStatus.ESCALATED,
            )
            .order_by(Escalation.id.asc())
        )
    ).scalars().all()
    items = [_serialize_escalation(escalation) for escalation in escalations]
    return EscalationQueueResponse(items=items, count=len(items))


@router.post(
    "/escalations/{escalation_id}/override",
    response_model=OperatorOverrideResponse,
)
async def execute_operator_override(
    escalation_id: UUID,
    body: OperatorOverrideRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(swarm_control_access),
) -> OperatorOverrideResponse:
    escalation = (
        await db.execute(
            select(Escalation)
            .options(
                selectinload(Escalation.decision).selectinload(TrustDecision.run)
            )
            .where(Escalation.id == escalation_id)
        )
    ).scalar_one_or_none()
    if escalation is None or escalation.decision is None or escalation.decision.run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found")
    if escalation.status != EscalationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escalation has already been resolved",
        )

    decision = escalation.decision
    run = decision.run
    escalation.status = EscalationStatus.RESOLVED

    if body.override_action in {OverrideAction.APPROVE, OverrideAction.MODIFY}:
        decision.status = TrustDecisionStatus.AUTO_APPROVED
        run.status = AgentRunStatus.COMPLETED
    else:
        decision.status = TrustDecisionStatus.BLOCKED
        run.status = AgentRunStatus.BLOCKED
    run.completed_at = utc_now()

    override = OperatorOverride(
        escalation_id=escalation.id,
        operator_email=user.email,
        override_action=body.override_action,
        final_payload=body.final_payload,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)

    return _serialize_override(override, escalation, decision)


@router.post(
    "/webhooks/streamline/test",
    response_model=StreamlineWebhookTestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_streamline_webhook(
    body: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamlineWebhookTestResponse:
    _require_loopback_client(request)

    agent = await _ensure_streamline_oracle_agent(db)
    run = await _create_agent_run(
        db,
        agent=agent,
        trigger_source="streamline_webhook_test",
    )

    oracle = StreamlineOracleAgent()
    try:
        proposed_transaction = await oracle.process_event(body, run_id=run.id)
    except ValidationError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Streamline Oracle returned an invalid structured payload.",
                "errors": exc.errors(),
                "run_id": str(run.id),
            },
        ) from exc
    except RuntimeError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "run_id": str(run.id)},
        ) from exc
    except ValueError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "run_id": str(run.id)},
        ) from exc
    except httpx.HTTPError as exc:
        await _mark_run_failed(db, run=run)
        detail: dict[str, Any] = {"message": f"Streamline Oracle transport failed: {exc}", "run_id": str(run.id)}
        if isinstance(exc, httpx.HTTPStatusError):
            detail["upstream_status"] = exc.response.status_code
            detail["upstream_body"] = exc.response.text
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc

    auditor = GRECAuditorAgent()
    try:
        audit_report = await auditor.audit_transaction(
            proposed_transaction,
            body,
            run_id=run.id,
        )
    except ValidationError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "GREC Auditor returned an invalid structured payload.",
                "errors": exc.errors(),
                "run_id": str(run.id),
            },
        ) from exc
    except RuntimeError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "run_id": str(run.id)},
        ) from exc
    except ValueError as exc:
        await _mark_run_failed(db, run=run)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "run_id": str(run.id)},
        ) from exc
    except httpx.HTTPError as exc:
        await _mark_run_failed(db, run=run)
        detail = {"message": f"GREC Auditor transport failed: {exc}", "run_id": str(run.id)}
        if isinstance(exc, httpx.HTTPStatusError):
            detail["upstream_status"] = exc.response.status_code
            detail["upstream_body"] = exc.response.text
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc

    proposed_payload = proposed_transaction.model_dump(mode="json")
    is_authorized = await policy_service.evaluate_agent_authorization(db, agent.name)
    policy_evaluation: dict[str, Any] = {
        "agent_authorized": is_authorized,
        "oracle_reasoning": proposed_transaction.reasoning,
        "grec_audit": audit_report.model_dump(mode="json"),
    }

    if not audit_report.is_compliant:
        policy_evaluation.update(
            {
                "auditor_compliant": False,
                "violations": audit_report.violations,
                "compliant": False,
                "reason_code": "grec_non_compliant",
            }
        )
        run_response = await _persist_run_decision(
            db,
            run=run,
            agent=agent,
            proposed_payload=proposed_payload,
            policy_evaluation=policy_evaluation,
            decision_status=TrustDecisionStatus.ESCALATED,
            deterministic_score=0.0,
        )
    else:
        policy_evaluation.update(policy_service.evaluate_trust_decision(proposed_payload))
        policy_evaluation["auditor_compliant"] = True
        compliant = bool(policy_evaluation.get("compliant")) and is_authorized
        policy_evaluation["compliant"] = compliant
        run_response = await _persist_run_decision(
            db,
            run=run,
            agent=agent,
            proposed_payload=proposed_payload,
            policy_evaluation=policy_evaluation,
            decision_status=(
                TrustDecisionStatus.AUTO_APPROVED
                if compliant
                else TrustDecisionStatus.ESCALATED
            ),
            deterministic_score=1.0 if compliant else 0.0,
        )

    if not run_response.decisions:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dispatch completed without creating a trust decision.",
        )

    decision = run_response.decisions[0]
    return StreamlineWebhookTestResponse(
        run_id=run_response.id,
        decision_id=decision.id,
        decision_status=decision.status,
        policy_evaluation=decision.policy_evaluation,
    )
