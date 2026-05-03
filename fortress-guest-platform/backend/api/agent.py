"""
AI Agent API — Autonomous orchestration and intelligence endpoints
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models import AgentResponseQueue, EmailMessage, FinancialApproval, SEOPatch, TaylorQuoteRequest
from backend.models.agent_queue import AgentQueue
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.staff import StaffUser
from backend.services.agentic_orchestrator import AgenticOrchestrator
from backend.services.openshell_audit import record_audit_event

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
orchestrator = AgenticOrchestrator()
logger = logging.getLogger(__name__)


class ManualAgentDispatchRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=500)
    context_payload: dict[str, object] = Field(default_factory=dict)
    target_node: str = Field(default="auto", max_length=64)
    task_id: str | None = Field(default=None, max_length=120)


class AgentWorkItem(BaseModel):
    id: str
    source: str
    source_label: str
    status: str
    title: str
    detail: str | None = None
    risk_level: str
    requires_human_approval: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    href: str
    assigned_to: str | None = None
    escalated: bool = False
    last_action: str | None = None
    last_action_by: str | None = None
    last_action_at: str | None = None
    actions: list[str] = Field(default_factory=list)


class AgentWorkItemsResponse(BaseModel):
    items: list[AgentWorkItem]
    total: int
    summary: dict[str, int]


class AgentWorkItemActionRequest(BaseModel):
    action: Literal["assign", "escalate", "dismiss", "mark_reviewed"]
    assignee: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=1000)


class AgentWorkItemActionResponse(BaseModel):
    ok: bool
    source: str
    id: str
    action: str
    status: str
    audit_id: str | None = None
    audit_hash: str | None = None
    message: str


class AgentWorkItemAuditEntry(BaseModel):
    id: str
    source: str
    source_label: str
    item_id: str | None = None
    action: str
    actor_email: str | None = None
    assignee: str | None = None
    note: str | None = None
    outcome: str
    created_at: str | None = None
    audit_hash: str


class AgentWorkItemAuditResponse(BaseModel):
    items: list[AgentWorkItemAuditEntry]
    total: int
    summary: dict[str, int]


class AgentQueueHealthSource(BaseModel):
    source: str
    source_label: str
    status: str
    pending_count: int
    failed_count: int
    action_count_24h: int
    oldest_pending_at: str | None = None
    oldest_pending_age_hours: float | None = None
    href: str


class AgentQueueHealthResponse(BaseModel):
    sources: list[AgentQueueHealthSource]
    summary: dict[str, int]
    generated_at: str


class AgentAutonomyGate(BaseModel):
    id: str
    label: str
    status: str
    risk_level: str
    human_approval_required: bool
    blockers: list[str] = Field(default_factory=list)
    signals: dict[str, int] = Field(default_factory=dict)
    href: str


class AgentAutonomyGatesResponse(BaseModel):
    gates: list[AgentAutonomyGate]
    summary: dict[str, int]
    generated_at: str


class AgentOperator(BaseModel):
    id: str
    label: str
    purpose: str
    status: str
    autonomy_level: str
    risk_level: str
    gate_id: str
    source: str | None = None
    queue_status: str | None = None
    pending_count: int = 0
    failed_count: int = 0
    human_approval_required: bool
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    data_scope: list[str] = Field(default_factory=list)
    href: str


class AgentOperatorsResponse(BaseModel):
    operators: list[AgentOperator]
    summary: dict[str, int]
    generated_at: str


SOURCE_LABELS = {
    "guest_concierge": "Guest Concierge",
    "hunter_reactivation": "Hunter Reactivation",
    "seo_content": "SEO Content",
    "taylor_quotes": "Taylor Quotes",
    "financial_variance": "Financial Variance",
    "email_intake": "Email Intake",
}

SOURCE_HREFS = {
    "guest_concierge": "/ai-engine",
    "hunter_reactivation": "/vrs/hunter",
    "seo_content": "/seo-review?status=pending_human",
    "taylor_quotes": "/vrs/quotes",
    "financial_variance": "/command/triage",
    "email_intake": "/email-intake",
}


def _nemoclaw_execute_url() -> str:
    base_url = str(settings.nemoclaw_orchestrator_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("NemoClaw orchestrator URL is not configured.")
    return f"{base_url}/api/agent/execute"


def _nemoclaw_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(settings.nemoclaw_orchestrator_api_key or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _streaming_headers() -> dict[str, str]:
    return {
        **_nemoclaw_headers(),
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }


def _nemoclaw_verify_ssl(base_url: str) -> bool:
    override = (os.getenv("NEMOCLAW_ORCHESTRATOR_VERIFY_SSL") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False

    host = (urlsplit(base_url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


def _manual_dispatch_payload(directive: ManualAgentDispatchRequest, current_user: StaffUser) -> tuple[str, dict[str, object]]:
    task_id = directive.task_id or f"manual-dispatch-{uuid4().hex[:12]}"
    return task_id, {
        "task_id": task_id,
        "intent": directive.intent,
        "context_payload": {
            **directive.context_payload,
            "target_node": directive.target_node,
            "requested_by": current_user.email,
        },
    }


def _sse_frame(payload: dict[str, object]) -> bytes:
    return f"data: {json.dumps(payload, default=str)}\n\n".encode("utf-8")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _summarize(items: list[AgentWorkItem]) -> dict[str, int]:
    summary: dict[str, int] = {
        "human_required": 0,
        "public_content": 0,
        "financial": 0,
        "guest_facing": 0,
        "failed": 0,
    }
    for item in items:
        summary[item.source] = summary.get(item.source, 0) + 1
        if item.requires_human_approval:
            summary["human_required"] += 1
        if item.risk_level == "public_content":
            summary["public_content"] += 1
        if item.risk_level == "financial":
            summary["financial"] += 1
        if item.risk_level == "guest_facing":
            summary["guest_facing"] += 1
        if item.status in {"failed", "send_failed"}:
            summary["failed"] += 1
    return summary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_naive() -> datetime:
    return datetime.utcnow()


def _age_hours(value) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        delta = _utc_now_naive() - value
    else:
        delta = _utc_now() - value.astimezone(timezone.utc)
    return round(max(delta.total_seconds(), 0) / 3600, 1)


def _resource_id(source: str, item_id: str) -> str:
    return f"{source}:{item_id}"


def _split_resource_id(resource_id: str | None) -> tuple[str, str | None]:
    if not resource_id or ":" not in resource_id:
        return "unknown", None
    source, item_id = resource_id.split(":", 1)
    return source, item_id or None


def _audit_summary(items: list[AgentWorkItemAuditEntry]) -> dict[str, int]:
    summary: dict[str, int] = {"total": len(items), "assign": 0, "escalate": 0, "dismiss": 0, "mark_reviewed": 0}
    for item in items:
        summary[item.action] = summary.get(item.action, 0) + 1
        summary[item.source] = summary.get(item.source, 0) + 1
    return summary


def _queue_source_status(pending_count: int, failed_count: int, oldest_pending_age_hours: float | None) -> str:
    if failed_count > 0:
        return "degraded"
    if pending_count >= 25:
        return "attention"
    if oldest_pending_age_hours is not None and oldest_pending_age_hours >= 24:
        return "attention"
    if pending_count > 0:
        return "watch"
    return "healthy"


async def _count_rows(db: AsyncSession, model, *conditions) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(*conditions))
    return int(result.scalar_one() or 0)


async def _oldest_value(db: AsyncSession, model, column, *conditions):
    result = await db.execute(select(column).select_from(model).where(*conditions).order_by(column.asc()).limit(1))
    return result.scalar_one_or_none()


async def _work_item_action_count_24h(db: AsyncSession, source: str) -> int:
    since = _utc_now_naive() - timedelta(hours=24)
    return await _count_rows(
        db,
        OpenShellAuditLog,
        OpenShellAuditLog.resource_type == "agent_work_item",
        OpenShellAuditLog.tool_name == "agent_work_items",
        OpenShellAuditLog.resource_id.startswith(f"{source}:"),
        OpenShellAuditLog.created_at >= since,
    )


def _queue_health_summary(sources: list[AgentQueueHealthSource]) -> dict[str, int]:
    return {
        "pending_total": sum(source.pending_count for source in sources),
        "failed_total": sum(source.failed_count for source in sources),
        "degraded_sources": sum(1 for source in sources if source.status == "degraded"),
        "attention_sources": sum(1 for source in sources if source.status in {"attention", "degraded"}),
        "action_count_24h": sum(source.action_count_24h for source in sources),
    }


async def _build_queue_health_source(
    db: AsyncSession,
    *,
    source: str,
    pending_count: int,
    failed_count: int,
    oldest_pending_at,
) -> AgentQueueHealthSource:
    oldest_age = _age_hours(oldest_pending_at)
    return AgentQueueHealthSource(
        source=source,
        source_label=SOURCE_LABELS[source],
        status=_queue_source_status(pending_count, failed_count, oldest_age),
        pending_count=pending_count,
        failed_count=failed_count,
        action_count_24h=await _work_item_action_count_24h(db, source),
        oldest_pending_at=_iso(oldest_pending_at),
        oldest_pending_age_hours=oldest_age,
        href=SOURCE_HREFS[source],
    )


async def _build_agent_queue_health_sources(db: AsyncSession) -> list[AgentQueueHealthSource]:
    return [
        await _build_queue_health_source(
            db,
            source="guest_concierge",
            pending_count=await _count_rows(db, AgentResponseQueue, AgentResponseQueue.status == "pending"),
            failed_count=0,
            oldest_pending_at=await _oldest_value(
                db,
                AgentResponseQueue,
                AgentResponseQueue.created_at,
                AgentResponseQueue.status == "pending",
            ),
        ),
        await _build_queue_health_source(
            db,
            source="hunter_reactivation",
            pending_count=await _count_rows(db, AgentQueue, AgentQueue.status == "pending_review"),
            failed_count=await _count_rows(db, AgentQueue, AgentQueue.status == "failed"),
            oldest_pending_at=await _oldest_value(
                db,
                AgentQueue,
                AgentQueue.created_at,
                AgentQueue.status == "pending_review",
            ),
        ),
        await _build_queue_health_source(
            db,
            source="seo_content",
            pending_count=await _count_rows(db, SEOPatch, SEOPatch.status.in_(["pending_human", "needs_rewrite"])),
            failed_count=await _count_rows(db, SEOPatch, SEOPatch.deploy_status == "failed"),
            oldest_pending_at=await _oldest_value(
                db,
                SEOPatch,
                SEOPatch.updated_at,
                SEOPatch.status.in_(["pending_human", "needs_rewrite"]),
            ),
        ),
        await _build_queue_health_source(
            db,
            source="taylor_quotes",
            pending_count=await _count_rows(db, TaylorQuoteRequest, TaylorQuoteRequest.status == "pending_approval"),
            failed_count=0,
            oldest_pending_at=await _oldest_value(
                db,
                TaylorQuoteRequest,
                TaylorQuoteRequest.created_at,
                TaylorQuoteRequest.status == "pending_approval",
            ),
        ),
        await _build_queue_health_source(
            db,
            source="financial_variance",
            pending_count=await _count_rows(db, FinancialApproval, FinancialApproval.status == "pending"),
            failed_count=0,
            oldest_pending_at=await _oldest_value(
                db,
                FinancialApproval,
                FinancialApproval.created_at,
                FinancialApproval.status == "pending",
            ),
        ),
        await _build_queue_health_source(
            db,
            source="email_intake",
            pending_count=await _count_rows(db, EmailMessage, EmailMessage.approval_status == "pending_approval"),
            failed_count=await _count_rows(db, EmailMessage, EmailMessage.approval_status == "send_failed"),
            oldest_pending_at=await _oldest_value(
                db,
                EmailMessage,
                EmailMessage.created_at,
                EmailMessage.approval_status == "pending_approval",
            ),
        ),
    ]


def _autonomy_gate_status(blockers: list[str], human_approval_required: bool) -> str:
    if blockers:
        return "locked"
    if human_approval_required:
        return "guarded"
    return "ready"


def _autonomy_gate_summary(gates: list[AgentAutonomyGate]) -> dict[str, int]:
    return {
        "locked": sum(1 for gate in gates if gate.status == "locked"),
        "guarded": sum(1 for gate in gates if gate.status == "guarded"),
        "ready": sum(1 for gate in gates if gate.status == "ready"),
        "blockers": sum(len(gate.blockers) for gate in gates),
        "human_approval_required": sum(1 for gate in gates if gate.human_approval_required),
    }


def _source_map(sources: list[AgentQueueHealthSource]) -> dict[str, AgentQueueHealthSource]:
    return {source.source: source for source in sources}


def _operator_status(source: AgentQueueHealthSource | None, gate_status: str, planned: bool = False) -> str:
    if planned:
        return "planned"
    if source and source.failed_count > 0:
        return "degraded"
    if gate_status == "locked":
        return "guarded"
    if source and source.pending_count > 0:
        return "reviewing"
    return "ready"


def _operator_summary(operators: list[AgentOperator]) -> dict[str, int]:
    return {
        "total": len(operators),
        "ready": sum(1 for operator in operators if operator.status == "ready"),
        "reviewing": sum(1 for operator in operators if operator.status == "reviewing"),
        "guarded": sum(1 for operator in operators if operator.status == "guarded"),
        "degraded": sum(1 for operator in operators if operator.status == "degraded"),
        "planned": sum(1 for operator in operators if operator.status == "planned"),
        "human_approval_required": sum(1 for operator in operators if operator.human_approval_required),
    }


def _operator_from_source(
    *,
    source: AgentQueueHealthSource | None,
    id: str,
    label: str,
    purpose: str,
    autonomy_level: str,
    risk_level: str,
    gate_id: str,
    gate_status: str,
    human_approval_required: bool,
    allowed_actions: list[str],
    blocked_actions: list[str],
    data_scope: list[str],
    href: str,
    planned: bool = False,
) -> AgentOperator:
    return AgentOperator(
        id=id,
        label=label,
        purpose=purpose,
        status=_operator_status(source, gate_status, planned=planned),
        autonomy_level=autonomy_level,
        risk_level=risk_level,
        gate_id=gate_id,
        source=source.source if source else None,
        queue_status=source.status if source else None,
        pending_count=source.pending_count if source else 0,
        failed_count=source.failed_count if source else 0,
        human_approval_required=human_approval_required,
        allowed_actions=allowed_actions,
        blocked_actions=blocked_actions,
        data_scope=data_scope,
        href=href,
    )


def _metadata_text(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None else None


def _work_item_actions(source: str, status: str) -> list[str]:
    if source == "seo_content" and status == "needs_rewrite":
        return ["assign", "dismiss", "mark_reviewed"]
    if status in {"pending", "pending_review", "pending_human", "pending_approval", "send_failed", "failed"}:
        return ["assign", "escalate", "dismiss", "mark_reviewed"]
    return []


def _set_work_item_metadata(existing: dict | None, key: str, payload: dict[str, object]) -> dict:
    metadata = dict(existing or {})
    metadata[key] = payload
    return metadata


def _action_metadata(
    *,
    source: str,
    item_id: str,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
) -> dict[str, object]:
    assignee = body.assignee or user.email
    return {
        "source": source,
        "item_id": item_id,
        "action": body.action,
        "assignee": assignee,
        "note": body.note,
        "actor_email": user.email,
        "acted_at": _utc_now().isoformat(),
    }


def _append_note(existing: str | None, note: str) -> str:
    if not existing:
        return note[:4000]
    return f"{existing}\n\n{note}"[:4000]


async def _apply_work_item_audit_state(db: AsyncSession, items: list[AgentWorkItem]) -> None:
    if not items:
        return

    by_resource_id = {_resource_id(item.source, item.id): item for item in items}
    result = await db.execute(
        select(OpenShellAuditLog)
        .where(
            OpenShellAuditLog.resource_type == "agent_work_item",
            OpenShellAuditLog.tool_name == "agent_work_items",
            OpenShellAuditLog.resource_id.in_(list(by_resource_id)),
        )
        .order_by(OpenShellAuditLog.created_at.asc())
        .limit(1000)
    )

    for audit in result.scalars().all():
        item = by_resource_id.get(audit.resource_id or "")
        if item is None:
            continue

        action = (audit.action or "").removeprefix("agent.work_item.")
        metadata = audit.metadata_json or {}
        if action == "assign":
            item.assigned_to = str(metadata.get("assignee") or audit.actor_email or "")
        elif action == "escalate":
            item.escalated = True

        item.last_action = action
        item.last_action_by = audit.actor_email
        item.last_action_at = _iso(audit.created_at)


def _parse_item_uuid(item_id: str) -> UUID:
    try:
        return UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid work item id") from exc


async def _load_work_item_row(db: AsyncSession, source: str, item_id: str):
    source = source.strip().lower()
    model_by_source = {
        "guest_concierge": AgentResponseQueue,
        "hunter_reactivation": AgentQueue,
        "seo_content": SEOPatch,
        "taylor_quotes": TaylorQuoteRequest,
        "financial_variance": FinancialApproval,
        "email_intake": EmailMessage,
    }
    model = model_by_source.get(source)
    if model is None:
        raise HTTPException(status_code=404, detail="Unknown work item source")

    row = await db.get(model, _parse_item_uuid(item_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return source, row


def _apply_agent_response_action(
    row: AgentResponseQueue,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    if body.action == "assign":
        row.decision_metadata = _set_work_item_metadata(row.decision_metadata, "work_item_assignment", metadata)
        return row.status
    if body.action == "escalate":
        row.escalation_reason = body.note or row.escalation_reason or f"Escalated by {user.email}"
        row.decision_metadata = _set_work_item_metadata(row.decision_metadata, "work_item_escalation", metadata)
        return row.status
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Work item is already {row.status}")
    row.status = "expired" if body.action == "mark_reviewed" else "rejected"
    row.reviewed_by = user.email
    row.reviewed_at = _utc_now_naive()
    row.decision_metadata = _set_work_item_metadata(row.decision_metadata, "work_item_resolution", metadata)
    return row.status


def _apply_hunter_action(
    row: AgentQueue,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    if body.action == "assign":
        return row.status
    if body.action == "escalate":
        note = body.note or f"Escalated by {user.email}"
        row.error_log = _append_note(row.error_log, note)
        return row.status
    if row.status not in {"pending_review", "failed"}:
        raise HTTPException(status_code=409, detail=f"Work item is already {row.status}")
    row.status = "rejected"
    row.error_log = body.note or row.error_log or f"{body.action.replace('_', ' ')} by {user.email}"
    row.updated_at = _utc_now()
    return row.status


def _apply_seo_action(
    row: SEOPatch,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    if body.action == "assign":
        return row.status
    if body.action == "escalate":
        if row.status == "pending_human":
            row.status = "needs_rewrite"
        return row.status
    if row.status not in {"pending_human", "needs_rewrite"}:
        raise HTTPException(status_code=409, detail=f"Work item is already {row.status}")
    row.status = "rejected"
    row.reviewed_by = user.email
    row.reviewed_at = _utc_now()
    return row.status


def _apply_taylor_action(
    row: TaylorQuoteRequest,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    if body.action in {"assign", "escalate"}:
        return row.status
    if row.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Work item is already {row.status}")
    row.status = "expired"
    row.updated_at = _utc_now()
    return row.status


def _apply_financial_action(
    row: FinancialApproval,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    key = {
        "assign": "work_item_assignment",
        "escalate": "work_item_escalation",
        "dismiss": "work_item_resolution",
        "mark_reviewed": "work_item_resolution",
    }[body.action]
    row.context_payload = _set_work_item_metadata(row.context_payload, key, metadata)
    if body.action in {"assign", "escalate"}:
        return row.status
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Work item is already {row.status}")
    row.status = "rejected"
    row.resolved_by = user.email
    row.resolved_at = _utc_now()
    return row.status


def _apply_email_action(
    row: EmailMessage,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    key = {
        "assign": "work_item_assignment",
        "escalate": "work_item_escalation",
        "dismiss": "work_item_resolution",
        "mark_reviewed": "work_item_resolution",
    }[body.action]
    row.extra_data = _set_work_item_metadata(row.extra_data, key, metadata)
    if body.action in {"assign", "escalate"}:
        return row.approval_status
    if row.approval_status not in {"pending_approval", "send_failed"}:
        raise HTTPException(status_code=409, detail=f"Work item is already {row.approval_status}")
    row.approval_status = "no_draft_needed" if body.action == "mark_reviewed" and row.approval_status == "pending_approval" else "rejected"
    row.human_reviewed_by = user.id
    row.human_reviewed_at = _utc_now()
    return row.approval_status


def _apply_work_item_action(
    source: str,
    row,
    *,
    body: AgentWorkItemActionRequest,
    user: StaffUser,
    metadata: dict[str, object],
) -> str:
    if source == "guest_concierge":
        return _apply_agent_response_action(row, body=body, user=user, metadata=metadata)
    if source == "hunter_reactivation":
        return _apply_hunter_action(row, body=body, user=user, metadata=metadata)
    if source == "seo_content":
        return _apply_seo_action(row, body=body, user=user, metadata=metadata)
    if source == "taylor_quotes":
        return _apply_taylor_action(row, body=body, user=user, metadata=metadata)
    if source == "financial_variance":
        return _apply_financial_action(row, body=body, user=user, metadata=metadata)
    if source == "email_intake":
        return _apply_email_action(row, body=body, user=user, metadata=metadata)
    raise HTTPException(status_code=404, detail="Unknown work item source")


@router.get("/stats")
async def agent_stats(db: AsyncSession = Depends(get_db)):
    """Get AI agent performance statistics."""
    return await orchestrator.get_agent_stats(db)


@router.get("/work-items", response_model=AgentWorkItemsResponse)
async def agent_work_items(
    limit: int = 80,
    db: AsyncSession = Depends(get_db),
):
    """Return a read-only unified view of existing agentic/HITL work queues."""
    per_queue_limit = max(5, min(limit, 200))
    items: list[AgentWorkItem] = []

    guest_responses = (
        await db.execute(
            select(AgentResponseQueue)
            .where(AgentResponseQueue.status == "pending")
            .order_by(AgentResponseQueue.created_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in guest_responses:
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="guest_concierge",
                source_label="Guest Concierge",
                status=row.status,
                title=row.intent or "Guest response draft",
                detail=row.escalation_reason or row.action or "AI response awaiting staff review",
                risk_level="guest_facing",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                href="/ai-engine",
            )
        )

    hunter_queue = (
        await db.execute(
            select(AgentQueue)
            .where(AgentQueue.status.in_(["pending_review", "failed"]))
            .order_by(AgentQueue.created_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in hunter_queue:
        detail = row.error_log if row.status == "failed" else row.delivery_channel
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="hunter_reactivation",
                source_label="Hunter Reactivation",
                status=row.status,
                title="Outbound recovery draft",
                detail=detail or "Reactivation message awaiting approval",
                risk_level="guest_facing",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                href="/vrs/hunter",
            )
        )

    seo_patches = (
        await db.execute(
            select(SEOPatch)
            .where(SEOPatch.status.in_(["pending_human", "needs_rewrite"]))
            .order_by(SEOPatch.updated_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in seo_patches:
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="seo_content",
                source_label="SEO Content",
                status=row.status,
                title=row.page_path,
                detail=f"score={row.godhead_score}" if row.godhead_score is not None else "SEO proposal awaiting review",
                risk_level="public_content",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                href="/seo-review?status=pending_human",
            )
        )

    taylor_quotes = (
        await db.execute(
            select(TaylorQuoteRequest)
            .where(TaylorQuoteRequest.status == "pending_approval")
            .order_by(TaylorQuoteRequest.created_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in taylor_quotes:
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="taylor_quotes",
                source_label="Taylor Quotes",
                status=row.status,
                title=row.guest_email,
                detail=f"{row.check_in} to {row.check_out} · {row.nights} nights",
                risk_level="guest_facing",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                href="/vrs/quotes",
            )
        )

    financial_approvals = (
        await db.execute(
            select(FinancialApproval)
            .where(FinancialApproval.status == "pending")
            .order_by(FinancialApproval.created_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in financial_approvals:
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="financial_variance",
                source_label="Financial Variance",
                status=row.status,
                title=row.reservation_id,
                detail=f"{row.discrepancy_type} · delta {row.delta_cents} cents",
                risk_level="financial",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.resolved_at),
                href="/command/triage",
            )
        )

    email_messages = (
        await db.execute(
            select(EmailMessage)
            .where(EmailMessage.approval_status.in_(["pending_approval", "send_failed"]))
            .order_by(EmailMessage.created_at.desc())
            .limit(per_queue_limit)
        )
    ).scalars().all()
    for row in email_messages:
        items.append(
            AgentWorkItem(
                id=str(row.id),
                source="email_intake",
                source_label="Email Intake",
                status=row.approval_status,
                title=row.subject or row.email_from,
                detail=row.error_message or row.body_excerpt or row.email_from,
                risk_level="guest_facing",
                created_at=_iso(row.created_at),
                updated_at=_iso(row.human_reviewed_at),
                href="/email-intake",
            )
        )

    items.sort(key=lambda item: item.created_at or "", reverse=True)
    items = items[: max(1, min(limit, 200))]
    for item in items:
        item.actions = _work_item_actions(item.source, item.status)
    await _apply_work_item_audit_state(db, items)

    return AgentWorkItemsResponse(items=items, total=len(items), summary=_summarize(items))


@router.get("/work-items/audit", response_model=AgentWorkItemAuditResponse)
async def agent_work_item_audit(
    limit: int = 80,
    source: str | None = None,
    item_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return the signed human-action trail for the unified agent work queue."""
    capped_limit = max(1, min(limit, 200))
    query = (
        select(OpenShellAuditLog)
        .where(
            OpenShellAuditLog.resource_type == "agent_work_item",
            OpenShellAuditLog.tool_name == "agent_work_items",
        )
        .order_by(OpenShellAuditLog.created_at.desc())
        .limit(capped_limit)
    )

    normalized_source = source.strip().lower() if source else None
    if item_id and not normalized_source:
        raise HTTPException(status_code=422, detail="source is required when filtering by item_id")
    if normalized_source and normalized_source not in SOURCE_LABELS:
        raise HTTPException(status_code=422, detail="Unknown work item source")
    if normalized_source and item_id:
        query = query.where(OpenShellAuditLog.resource_id == _resource_id(normalized_source, item_id))
    elif normalized_source:
        query = query.where(OpenShellAuditLog.resource_id.startswith(f"{normalized_source}:"))

    result = await db.execute(query)
    items: list[AgentWorkItemAuditEntry] = []
    for row in result.scalars().all():
        row_source, row_item_id = _split_resource_id(row.resource_id)
        metadata = row.metadata_json or {}
        action = (row.action or "").removeprefix("agent.work_item.")
        items.append(
            AgentWorkItemAuditEntry(
                id=str(row.id),
                source=row_source,
                source_label=SOURCE_LABELS.get(row_source, row_source.replace("_", " ").title()),
                item_id=row_item_id,
                action=action,
                actor_email=row.actor_email,
                assignee=_metadata_text(metadata, "assignee"),
                note=_metadata_text(metadata, "note"),
                outcome=row.outcome,
                created_at=_iso(row.created_at),
                audit_hash=row.entry_hash,
            )
        )

    return AgentWorkItemAuditResponse(items=items, total=len(items), summary=_audit_summary(items))


@router.get("/queue-health", response_model=AgentQueueHealthResponse)
async def agent_queue_health(db: AsyncSession = Depends(get_db)):
    """Return read-only health signals for the queues feeding the agent control layer."""
    sources = await _build_agent_queue_health_sources(db)
    return AgentQueueHealthResponse(
        sources=sources,
        summary=_queue_health_summary(sources),
        generated_at=_utc_now().isoformat(),
    )


@router.get("/operators", response_model=AgentOperatorsResponse)
async def agent_operators(db: AsyncSession = Depends(get_db)):
    """Return the bounded agent operator registry with live queue signals."""
    sources = await _build_agent_queue_health_sources(db)
    by_source = _source_map(sources)
    queue_summary = _queue_health_summary(sources)

    guest_sources = [
        by_source["guest_concierge"],
        by_source["hunter_reactivation"],
        by_source["taylor_quotes"],
        by_source["email_intake"],
    ]
    guest_pending = sum(source.pending_count for source in guest_sources)
    guest_failed = sum(source.failed_count for source in guest_sources)
    guest_gate_status = "locked" if guest_pending or guest_failed else "guarded"
    seo_gate_status = "locked" if by_source["seo_content"].pending_count or by_source["seo_content"].failed_count else "guarded"
    financial_gate_status = "locked" if by_source["financial_variance"].pending_count else "guarded"
    reliability_gate_status = "locked" if queue_summary["failed_total"] or queue_summary["attention_sources"] else "ready"

    operators = [
        _operator_from_source(
            source=by_source["guest_concierge"],
            id="guest_concierge",
            label="Guest Concierge",
            purpose="Classify inbound guest messages and draft responses for staff review.",
            autonomy_level="draft_only",
            risk_level="guest_facing",
            gate_id="guest_facing",
            gate_status=guest_gate_status,
            human_approval_required=True,
            allowed_actions=["classify_intent", "draft_response", "recommend_work_order"],
            blocked_actions=["send_guest_commitment", "issue_refund", "give_legal_position"],
            data_scope=["messages", "guests", "reservations", "property_knowledge"],
            href="/ai-engine",
        ),
        _operator_from_source(
            source=by_source["email_intake"],
            id="email_intake",
            label="Email Intake Agent",
            purpose="Classify inbound email and prepare outbound drafts for human approval.",
            autonomy_level="draft_only",
            risk_level="guest_facing",
            gate_id="guest_facing",
            gate_status=guest_gate_status,
            human_approval_required=True,
            allowed_actions=["classify_email", "draft_reply", "link_guest_context"],
            blocked_actions=["send_email_without_approval", "change_reservation_terms"],
            data_scope=["email_messages", "email_inquirers", "guests", "reservations"],
            href="/email-intake",
        ),
        _operator_from_source(
            source=by_source["hunter_reactivation"],
            id="hunter_reactivation",
            label="Hunter Reactivation",
            purpose="Draft outbound recovery messages for abandoned or stale guest opportunities.",
            autonomy_level="draft_only",
            risk_level="guest_facing",
            gate_id="guest_facing",
            gate_status=guest_gate_status,
            human_approval_required=True,
            allowed_actions=["draft_reactivation", "score_recovery_target"],
            blocked_actions=["send_reactivation_without_approval", "offer_unapproved_discount"],
            data_scope=["guests", "agent_queue", "historical_recovery"],
            href="/vrs/hunter",
        ),
        _operator_from_source(
            source=by_source["taylor_quotes"],
            id="quote_concierge",
            label="Quote Concierge",
            purpose="Prepare multi-property quote options and route them for staff approval.",
            autonomy_level="prepare_only",
            risk_level="guest_facing",
            gate_id="guest_facing",
            gate_status=guest_gate_status,
            human_approval_required=True,
            allowed_actions=["assemble_quote_options", "freeze_quote_snapshot"],
            blocked_actions=["send_quote_without_approval", "alter_pricing_after_review"],
            data_scope=["properties", "rates", "fees", "taxes", "guest_quotes"],
            href="/vrs/quotes",
        ),
        _operator_from_source(
            source=by_source["seo_content"],
            id="seo_content",
            label="SEO Content Agent",
            purpose="Draft and grade SEO/content proposals for public pages.",
            autonomy_level="draft_only",
            risk_level="public_content",
            gate_id="public_content",
            gate_status=seo_gate_status,
            human_approval_required=True,
            allowed_actions=["draft_metadata", "grade_patch", "request_rewrite"],
            blocked_actions=["publish_public_content_without_approval", "change_legacy_redirects"],
            data_scope=["seo_patches", "properties", "storefront_content", "rubrics"],
            href="/seo-review?status=pending_human",
        ),
        _operator_from_source(
            source=by_source["financial_variance"],
            id="reservation_auditor",
            label="Reservation Auditor",
            purpose="Compare local records against upstream financial and booking references.",
            autonomy_level="flag_only",
            risk_level="financial",
            gate_id="financial",
            gate_status=financial_gate_status,
            human_approval_required=True,
            allowed_actions=["detect_variance", "explain_delta", "queue_triage"],
            blocked_actions=["absorb_variance", "invoice_guest", "change_ledger"],
            data_scope=["reservations", "financial_approvals", "streamline_payloads", "quotes"],
            href="/command/triage",
        ),
        _operator_from_source(
            source=by_source["financial_variance"],
            id="finance_handoff",
            label="Finance Handoff Agent",
            purpose="Prepare finance exceptions and owner-facing handoff notes.",
            autonomy_level="prepare_only",
            risk_level="financial",
            gate_id="financial",
            gate_status=financial_gate_status,
            human_approval_required=True,
            allowed_actions=["summarize_exception", "prepare_handoff"],
            blocked_actions=["send_owner_report", "move_money", "close_financial_exception"],
            data_scope=["financial_approvals", "owner_statements", "reservations"],
            href="/command/triage",
        ),
        _operator_from_source(
            source=None,
            id="maintenance_dispatcher",
            label="Maintenance Dispatcher",
            purpose="Prepare maintenance and housekeeping tasks from guest/operations signals.",
            autonomy_level="planned",
            risk_level="irreversible",
            gate_id="irreversible",
            gate_status=reliability_gate_status,
            human_approval_required=True,
            allowed_actions=["draft_work_order", "suggest_vendor", "prioritize_issue"],
            blocked_actions=["dispatch_vendor_without_approval", "promise_guest_resolution"],
            data_scope=["work_orders", "messages", "properties", "vendors"],
            href="/work-orders",
            planned=True,
        ),
        _operator_from_source(
            source=None,
            id="owner_reporting",
            label="Owner Reporting Agent",
            purpose="Draft owner summaries and operational exception reports.",
            autonomy_level="planned",
            risk_level="financial",
            gate_id="financial",
            gate_status=financial_gate_status,
            human_approval_required=True,
            allowed_actions=["draft_owner_summary", "surface_exceptions"],
            blocked_actions=["send_owner_report_without_approval", "state_final_financials"],
            data_scope=["owner_statements", "reservations", "financial_approvals"],
            href="/admin/payouts",
            planned=True,
        ),
    ]

    return AgentOperatorsResponse(
        operators=operators,
        summary=_operator_summary(operators),
        generated_at=_utc_now().isoformat(),
    )


@router.get("/autonomy-gates", response_model=AgentAutonomyGatesResponse)
async def agent_autonomy_gates(db: AsyncSession = Depends(get_db)):
    """Return human-approval gates that constrain agent autonomy in production."""
    sources = await _build_agent_queue_health_sources(db)
    by_source = _source_map(sources)
    queue_summary = _queue_health_summary(sources)

    guest_sources = [
        by_source["guest_concierge"],
        by_source["hunter_reactivation"],
        by_source["taylor_quotes"],
        by_source["email_intake"],
    ]
    guest_pending = sum(source.pending_count for source in guest_sources)
    guest_failed = sum(source.failed_count for source in guest_sources)
    guest_blockers: list[str] = []
    if guest_pending:
        guest_blockers.append(f"{guest_pending} guest-facing item{'s' if guest_pending != 1 else ''} awaiting review")
    if guest_failed:
        guest_blockers.append(f"{guest_failed} guest-facing delivery failure{'s' if guest_failed != 1 else ''}")

    seo = by_source["seo_content"]
    seo_blockers: list[str] = []
    if seo.pending_count:
        seo_blockers.append(f"{seo.pending_count} SEO/content item{'s' if seo.pending_count != 1 else ''} awaiting review")
    if seo.failed_count:
        seo_blockers.append(f"{seo.failed_count} SEO deployment failure{'s' if seo.failed_count != 1 else ''}")

    financial = by_source["financial_variance"]
    financial_blockers: list[str] = []
    if financial.pending_count:
        financial_blockers.append(f"{financial.pending_count} financial variance item{'s' if financial.pending_count != 1 else ''} awaiting triage")

    reliability_blockers: list[str] = []
    if queue_summary["failed_total"]:
        reliability_blockers.append(f"{queue_summary['failed_total']} failed item{'s' if queue_summary['failed_total'] != 1 else ''} across agent queues")
    if queue_summary["attention_sources"]:
        reliability_blockers.append(f"{queue_summary['attention_sources']} queue source{'s' if queue_summary['attention_sources'] != 1 else ''} need attention")

    audit_blockers: list[str] = []
    if queue_summary["pending_total"] and not queue_summary["action_count_24h"]:
        audit_blockers.append("Pending work exists but no staff action has been recorded in the last 24 hours")

    gates = [
        AgentAutonomyGate(
            id="guest_facing",
            label="Guest-Facing Communication",
            status=_autonomy_gate_status(guest_blockers, True),
            risk_level="guest_facing",
            human_approval_required=True,
            blockers=guest_blockers,
            signals={"pending": guest_pending, "failed": guest_failed},
            href="/ai-engine",
        ),
        AgentAutonomyGate(
            id="public_content",
            label="Public Content And SEO",
            status=_autonomy_gate_status(seo_blockers, True),
            risk_level="public_content",
            human_approval_required=True,
            blockers=seo_blockers,
            signals={"pending": seo.pending_count, "failed": seo.failed_count},
            href="/seo-review?status=pending_human",
        ),
        AgentAutonomyGate(
            id="financial",
            label="Financial Actions",
            status=_autonomy_gate_status(financial_blockers, True),
            risk_level="financial",
            human_approval_required=True,
            blockers=financial_blockers,
            signals={"pending": financial.pending_count, "failed": financial.failed_count},
            href="/command/triage",
        ),
        AgentAutonomyGate(
            id="irreversible",
            label="Irreversible Operations",
            status=_autonomy_gate_status(reliability_blockers, True),
            risk_level="irreversible",
            human_approval_required=True,
            blockers=reliability_blockers,
            signals={
                "pending": queue_summary["pending_total"],
                "failed": queue_summary["failed_total"],
                "attention_sources": queue_summary["attention_sources"],
            },
            href="/ai-engine",
        ),
        AgentAutonomyGate(
            id="queue_reliability",
            label="Queue Reliability",
            status=_autonomy_gate_status(reliability_blockers, False),
            risk_level="operational",
            human_approval_required=False,
            blockers=reliability_blockers,
            signals={
                "pending": queue_summary["pending_total"],
                "failed": queue_summary["failed_total"],
                "attention_sources": queue_summary["attention_sources"],
            },
            href="/ai-engine",
        ),
        AgentAutonomyGate(
            id="audit_coverage",
            label="Audit Coverage",
            status=_autonomy_gate_status(audit_blockers, False),
            risk_level="compliance",
            human_approval_required=False,
            blockers=audit_blockers,
            signals={
                "pending": queue_summary["pending_total"],
                "actions_24h": queue_summary["action_count_24h"],
            },
            href="/ai-engine",
        ),
    ]

    return AgentAutonomyGatesResponse(
        gates=gates,
        summary=_autonomy_gate_summary(gates),
        generated_at=_utc_now().isoformat(),
    )


@router.post("/work-items/{source}/{item_id}/action", response_model=AgentWorkItemActionResponse)
async def agent_work_item_action(
    source: str,
    item_id: str,
    body: AgentWorkItemActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(CONTROL_ACCESS),
):
    """
    Record a guarded staff action against a unified work item.

    These controls are intentionally non-dispatching: approving/sending guest
    content, publishing SEO changes, or resolving money movement stays on the
    dedicated source screen where the full context and existing safeguards live.
    """
    source, row = await _load_work_item_row(db, source, item_id)
    metadata = _action_metadata(source=source, item_id=item_id, body=body, user=current_user)
    status_after = _apply_work_item_action(
        source,
        row,
        body=body,
        user=current_user,
        metadata=metadata,
    )
    audit_row = await record_audit_event(
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action=f"agent.work_item.{body.action}",
        resource_type="agent_work_item",
        resource_id=_resource_id(source, item_id),
        purpose="agentic_hitl_control",
        tool_name="agent_work_items",
        redaction_status="metadata_only",
        model_route="human_review",
        outcome="success",
        metadata_json=metadata,
        db=db,
    )
    if audit_row is None:
        raise HTTPException(status_code=500, detail="Work item action could not be audited")

    return AgentWorkItemActionResponse(
        ok=True,
        source=source,
        id=item_id,
        action=body.action,
        status=status_after,
        audit_id=str(audit_row.id),
        audit_hash=audit_row.entry_hash,
        message=f"{body.action.replace('_', ' ').title()} recorded",
    )


@router.post("/run-daily")
async def run_daily_automation(db: AsyncSession = Depends(get_db)):
    """Manually trigger the daily automation run."""
    return await orchestrator.run_daily_automation(db)


@router.post("/run-lifecycle")
async def run_lifecycle(db: AsyncSession = Depends(get_db)):
    """Manually trigger the lifecycle engine (pre-arrival, checkout, etc)."""
    from backend.services.lifecycle_engine import LifecycleEngine
    engine = LifecycleEngine(db)
    results = await engine.process_all_lifecycle_events()
    return {"ok": True, "results": results}


@router.get("/templates")
async def list_templates():
    """List all available response templates."""
    try:
        templates = {}
        for name, tmpl in orchestrator.RESPONSE_TEMPLATES.items():
            templates[name] = tmpl[:80] + "..." if len(tmpl) > 80 else tmpl
        return {"templates": templates, "count": len(templates)}
    except Exception:
        return {"templates": {}, "count": 0}


@router.post("/dispatch")
async def manual_agent_dispatch(
    directive: ManualAgentDispatchRequest,
    current_user: StaffUser = Depends(CONTROL_ACCESS),
):
    """Pushes a manual directive from the Command Center directly into NemoClaw."""
    task_id, payload = _manual_dispatch_payload(directive, current_user)
    logger.info("manual_agent_dispatch_requested", extra={"user": current_user.email, "intent": directive.intent[:120]})

    try:
        execute_url = _nemoclaw_execute_url()
        async with httpx.AsyncClient(timeout=60.0, verify=_nemoclaw_verify_ssl(execute_url)) as client:
            response = await client.post(
                execute_url,
                json=payload,
                headers=_nemoclaw_headers(),
            )
            response.raise_for_status()
            return response.json() if response.content else {"task_id": task_id, "status": "accepted"}
    except httpx.HTTPStatusError as exc:
        logger.error("manual_agent_dispatch_http_error", extra={"detail": exc.response.text[:400]})
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Matrix execution failed.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Orchestrator unreachable: {str(exc)[:300]}",
        ) from exc


@router.post("/dispatch/stream")
async def stream_agent_dispatch(
    directive: ManualAgentDispatchRequest,
    current_user: StaffUser = Depends(CONTROL_ACCESS),
):
    """Streams matrix execution updates and the final payload to the Command Center."""
    task_id, payload = _manual_dispatch_payload(directive, current_user)
    execute_url = _nemoclaw_execute_url()
    stream_url = f"{execute_url}/stream"
    verify_ssl = _nemoclaw_verify_ssl(execute_url)
    logger.info(
        "stream_agent_dispatch_requested",
        extra={"user": current_user.email, "intent": directive.intent[:120], "task_id": task_id},
    )

    async def event_generator():
        yield _sse_frame(
            {
                "task_id": task_id,
                "log": f"Dispatching {directive.intent} to NemoClaw...",
            }
        )

        try:
            async with httpx.AsyncClient(timeout=120.0, verify=verify_ssl) as client:
                async with client.stream(
                    "POST",
                    stream_url,
                    json=payload,
                    headers=_streaming_headers(),
                ) as response:
                    content_type = (response.headers.get("content-type") or "").lower()
                    if response.status_code not in {404, 405, 501}:
                        response.raise_for_status()
                        if "text/event-stream" in content_type:
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    yield chunk
                            return

                # Graceful fallback while NemoClaw only exposes the one-shot execute path.
                yield _sse_frame(
                    {
                        "task_id": task_id,
                        "log": "Live worker stream unavailable, relaying final NemoClaw result...",
                    }
                )

                response = await client.post(
                    execute_url,
                    json=payload,
                    headers=_nemoclaw_headers(),
                )
                response.raise_for_status()
                result = response.json() if response.content else {"task_id": task_id, "status": "accepted"}
                action_log = result.get("action_log")
                if isinstance(action_log, list):
                    for entry in action_log[:12]:
                        if isinstance(entry, str) and entry.strip():
                            yield _sse_frame({"task_id": task_id, "log": entry})
                yield _sse_frame(result)
        except httpx.HTTPStatusError as exc:
            yield _sse_frame(
                {
                    "task_id": task_id,
                    "error": "Matrix execution failed",
                    "details": str(exc)[:300],
                }
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse_frame(
                {
                    "task_id": task_id,
                    "error": "Orchestrator unreachable",
                    "details": str(exc)[:300],
                }
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
