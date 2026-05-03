"""
AI Agent API — Autonomous orchestration and intelligence endpoints
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models import AgentResponseQueue, EmailMessage, FinancialApproval, SEOPatch, TaylorQuoteRequest
from backend.models.agent_queue import AgentQueue
from backend.services.agentic_orchestrator import AgenticOrchestrator

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


class AgentWorkItemsResponse(BaseModel):
    items: list[AgentWorkItem]
    total: int
    summary: dict[str, int]


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

    return AgentWorkItemsResponse(items=items, total=len(items), summary=_summarize(items))


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
