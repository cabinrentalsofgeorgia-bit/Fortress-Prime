"""
Paperclip BYOA bridge — control-plane webhooks into the sovereign execution plane.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config import settings
from backend.core.security_swarm import verify_swarm_token

router = APIRouter()
logger = logging.getLogger(__name__)


class PaperclipWorkspace(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cwd: str | None = None
    source: str | None = None


class PaperclipWakeContext(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task_id: str | None = Field(default=None, alias="taskId")
    wake_reason: str | None = Field(default=None, alias="wakeReason")
    paperclip_workspace: PaperclipWorkspace | None = Field(
        default=None,
        alias="paperclipWorkspace",
    )


class PaperclipExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(alias="runId", min_length=1, max_length=128)
    agent_id: str = Field(alias="agentId", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    task_id: str | None = Field(default=None, alias="taskId", max_length=128)
    issue_id: str | None = Field(default=None, alias="issueId", max_length=128)
    wake_reason: str = Field(alias="wakeReason", min_length=1, max_length=64)
    wake_comment_id: str | None = Field(default=None, alias="wakeCommentId", max_length=128)
    approval_id: str | None = Field(default=None, alias="approvalId", max_length=128)
    approval_status: str | None = Field(default=None, alias="approvalStatus", max_length=64)
    issue_ids: list[str] = Field(default_factory=list, alias="issueIds")
    context: PaperclipWakeContext


class PaperclipAcceptedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["accepted"]
    execution_id: str = Field(alias="executionId")


class PaperclipUsagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    input_tokens: int | None = Field(default=None, alias="inputTokens", ge=0)
    output_tokens: int | None = Field(default=None, alias="outputTokens", ge=0)
    cached_input_tokens: int | None = Field(default=None, alias="cachedInputTokens", ge=0)


class PaperclipCallbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["succeeded", "failed"]
    result: str | None = None
    error_message: str | None = Field(default=None, alias="errorMessage")
    usage: PaperclipUsagePayload | None = None
    cost_usd: float | None = Field(default=None, alias="costUsd", ge=0)
    model: str | None = None
    provider: str | None = None


class NemoClawResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(alias="task_id")
    status: str
    action_log: list[str] = Field(default_factory=list)
    result_payload: dict[str, Any] | None = Field(default=None, alias="result_payload")


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


def _verify_ssl(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


def _paperclip_control_plane_url() -> str:
    base_url = str(settings.paperclip_control_plane_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("Paperclip control-plane URL is not configured.")
    return base_url


def _paperclip_callback_headers() -> dict[str, str]:
    api_key = str(settings.paperclip_control_plane_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Paperclip control-plane API key is not configured.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _paperclip_callback_url(run_id: str) -> str:
    return f"{_paperclip_control_plane_url()}/api/heartbeat-runs/{run_id}/callback"


def _directive_task_id(payload: PaperclipExecuteRequest) -> str:
    return payload.task_id or payload.issue_id or f"paperclip-run-{payload.run_id}"


def _directive_intent(payload: PaperclipExecuteRequest) -> str:
    return (
        f"Paperclip heartbeat wake={payload.wake_reason} "
        f"agent={payload.agent_id} "
        f"company={payload.company_id}"
    )


def _directive_payload(payload: PaperclipExecuteRequest) -> dict[str, Any]:
    return {
        "task_id": _directive_task_id(payload),
        "intent": _directive_intent(payload),
        "context_payload": {
            "bridge_source": "paperclip_http_adapter",
            "paperclip_run_id": payload.run_id,
            "paperclip_agent_id": payload.agent_id,
            "paperclip_company_id": payload.company_id,
            "paperclip_task_id": payload.task_id,
            "paperclip_issue_id": payload.issue_id,
            "paperclip_issue_ids": payload.issue_ids,
            "paperclip_wake_reason": payload.wake_reason,
            "paperclip_wake_comment_id": payload.wake_comment_id,
            "paperclip_approval_id": payload.approval_id,
            "paperclip_approval_status": payload.approval_status,
            "paperclip_context": payload.context.model_dump(by_alias=True),
            "paperclip_request": payload.model_dump(by_alias=True),
        },
    }


def _callback_result_text(
    payload: PaperclipExecuteRequest,
    nemoclaw: NemoClawResponse,
) -> str:
    envelope = {
        "runId": payload.run_id,
        "agentId": payload.agent_id,
        "taskId": _directive_task_id(payload),
        "wakeReason": payload.wake_reason,
        "nemoclawStatus": nemoclaw.status,
        "actionLog": nemoclaw.action_log,
        "resultPayload": nemoclaw.result_payload or {},
    }
    return json.dumps(envelope, default=str, sort_keys=True)


async def _send_paperclip_callback(
    run_id: str,
    callback_payload: PaperclipCallbackPayload,
) -> None:
    callback_url = _paperclip_callback_url(run_id)
    async with httpx.AsyncClient(timeout=30.0, verify=_verify_ssl(callback_url)) as client:
        response = await client.post(
            callback_url,
            json=callback_payload.model_dump(by_alias=True, exclude_none=True),
            headers=_paperclip_callback_headers(),
        )
        response.raise_for_status()


async def _process_paperclip_run(payload: PaperclipExecuteRequest) -> None:
    execute_url = _nemoclaw_execute_url()
    logger.info(
        "paperclip_bridge_dispatch_started",
        extra={
            "run_id": payload.run_id,
            "agent_id": payload.agent_id,
            "task_id": _directive_task_id(payload),
            "wake_reason": payload.wake_reason,
        },
    )

    try:
        async with httpx.AsyncClient(timeout=300.0, verify=_verify_ssl(execute_url)) as client:
            response = await client.post(
                execute_url,
                json=_directive_payload(payload),
                headers=_nemoclaw_headers(),
            )
            response.raise_for_status()
            nemoclaw = NemoClawResponse.model_validate(response.json())

        normalized_status = nemoclaw.status.strip().lower()
        callback_payload = PaperclipCallbackPayload(
            status="failed" if normalized_status in {"failed", "error"} else "succeeded",
            result=_callback_result_text(payload, nemoclaw),
            errorMessage=None if normalized_status not in {"failed", "error"} else _callback_result_text(payload, nemoclaw),
        )
        await _send_paperclip_callback(payload.run_id, callback_payload)
        logger.info(
            "paperclip_bridge_dispatch_completed",
            extra={
                "run_id": payload.run_id,
                "agent_id": payload.agent_id,
                "task_id": nemoclaw.task_id,
                "status": nemoclaw.status,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_bridge_dispatch_failed",
            extra={
                "run_id": payload.run_id,
                "agent_id": payload.agent_id,
                "wake_reason": payload.wake_reason,
            },
        )
        callback_payload = PaperclipCallbackPayload(
            status="failed",
            errorMessage=str(exc)[:500],
        )
        try:
            await _send_paperclip_callback(payload.run_id, callback_payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "paperclip_bridge_callback_failed",
                extra={"run_id": payload.run_id},
            )


@router.post(
    "/execute",
    response_model=PaperclipAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_paperclip_run(
    payload: PaperclipExecuteRequest,
    _swarm_token: str = Depends(verify_swarm_token),
) -> PaperclipAcceptedResponse:
    try:
        _paperclip_callback_url(payload.run_id)
        _paperclip_callback_headers()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    asyncio.create_task(_process_paperclip_run(payload))
    return PaperclipAcceptedResponse(status="accepted", executionId=payload.run_id)
