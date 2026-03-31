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
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.services.agentic_orchestrator import AgenticOrchestrator

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
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
