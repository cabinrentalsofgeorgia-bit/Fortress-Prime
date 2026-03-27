"""
AI Agent API — Autonomous orchestration and intelligence endpoints
"""
from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS
from backend.core.config import settings
from backend.core.database import get_db
from backend.models.staff import StaffUser
from backend.services.agentic_orchestrator import AgenticOrchestrator

router = APIRouter()
orchestrator = AgenticOrchestrator()
logger = logging.getLogger(__name__)


class ManualAgentDispatchRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=500)
    context_payload: dict[str, object] = Field(default_factory=dict)
    target_node: str = Field(default="auto", max_length=64)
    task_id: str | None = Field(default=None, max_length=120)


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


@router.get("/stats")
async def agent_stats(db: AsyncSession = Depends(get_db)):
    """Get AI agent performance statistics."""
    return await orchestrator.get_agent_stats(db)


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
    task_id = directive.task_id or f"manual-dispatch-{uuid4().hex[:12]}"
    payload = {
        "task_id": task_id,
        "intent": directive.intent,
        "context_payload": {
            **directive.context_payload,
            "target_node": directive.target_node,
            "requested_by": current_user.email,
        },
    }
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
