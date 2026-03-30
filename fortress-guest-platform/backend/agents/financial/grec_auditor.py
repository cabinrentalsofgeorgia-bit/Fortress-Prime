"""
Frontier-model GREC audit layer for trust-ledger proposals.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx

from backend.agents.financial.schemas import GRECAuditReport, ProposedTransaction
from backend.core.config import settings

logger = logging.getLogger("trust_swarm")
logger.setLevel(logging.INFO)

DEFAULT_AUDITOR_MODEL = "gpt-4o"
AUDITOR_TIMEOUT_SECONDS = 90.0
GREC_AUDITOR_SYSTEM_PROMPT = (
    "You are a strict GREC Trust Accounting Auditor. "
    "Your job is to review a proposed double-entry transaction. "
    "Rules: "
    "1. Guest advance deposits cannot be recognized as operating revenue until after check-out. "
    "2. Management commissions cannot be deducted from the Trust account prior to the revenue being earned. "
    "3. If commingling is detected, you must flag it as non-compliant. "
    "Return only a JSON object matching the GRECAuditReport payload."
)


class GRECAuditorAgent:
    """Routes compliance review through the LiteLLM frontier lane."""

    def __init__(self) -> None:
        self.base_url = _chat_completions_url(str(settings.litellm_base_url or "").strip())
        self.api_key = str(settings.litellm_master_key or "").strip()
        configured_openai_model = str(settings.openai_model or "").strip()
        self.model_name = (
            DEFAULT_AUDITOR_MODEL
            if configured_openai_model == "gpt-4-turbo-preview"
            else configured_openai_model or DEFAULT_AUDITOR_MODEL
        )

    async def audit_transaction(
        self,
        transaction: ProposedTransaction,
        event_context: dict[str, Any],
        *,
        run_id: UUID | None = None,
    ) -> GRECAuditReport:
        if not self.base_url:
            raise RuntimeError("LITELLM_BASE_URL is not configured for GREC audit routing.")
        if not self.api_key:
            raise RuntimeError("LITELLM_MASTER_KEY is not configured for GREC audit routing.")

        sanitized_context = _sanitize_event_context(event_context)
        request_payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": GREC_AUDITOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "event_context": sanitized_context,
                            "transaction": transaction.model_dump(mode="json"),
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        default=str,
                    ),
                },
            ],
            "temperature": 0.0,
            "max_tokens": 700,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        _log_inference_event(
            "grec_auditor_request",
            run_id=run_id,
            model_name=self.model_name,
            payload=request_payload,
        )

        response_payload = await self._post_json(
            self.base_url,
            api_key=self.api_key,
            request_payload=request_payload,
            run_id=run_id,
            event_name="grec_auditor_litellm_response_error",
        )

        raw_message = _extract_message_content(response_payload)
        usage = response_payload.get("usage") or {}
        _log_inference_event(
            "grec_auditor_response",
            run_id=run_id,
            model_name=self.model_name,
            payload={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "raw_response": raw_message,
            },
        )

        parsed = _normalize_audit_payload(_extract_json_object(raw_message))
        return GRECAuditReport.model_validate(parsed)

    async def _post_json(
        self,
        url: str,
        *,
        api_key: str,
        request_payload: dict[str, Any],
        run_id: UUID | None,
        event_name: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=AUDITOR_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            if response.is_error:
                _log_inference_event(
                    event_name,
                    run_id=run_id,
                    model_name=self.model_name,
                    payload={
                        "status_code": response.status_code,
                        "response_body": response.text,
                        "url": url,
                    },
                )
                response.raise_for_status()
            return response.json()


def _chat_completions_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return f"{value}/chat/completions"
    return f"{value}/v1/chat/completions"


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("GREC Auditor response did not contain choices.")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        stripped = content.strip()
        if stripped:
            return stripped

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        joined = "\n".join(text_parts).strip()
        if joined:
            return joined

    raise ValueError("GREC Auditor response did not contain text content.")


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in GREC Auditor output.")

    parsed = json.loads(raw_text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Structured output must decode to a JSON object.")
    return parsed


def _normalize_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("GRECAuditReport")
    normalized = candidate if isinstance(candidate, dict) else payload
    if "is_compliant" in normalized and "violations" in normalized:
        return normalized

    compliance_status = str(normalized.get("compliance_status") or "").strip().lower()
    issues = normalized.get("issues")
    if not isinstance(issues, list):
        issues = normalized.get("issues_detected")
    violations = [str(item).strip() for item in issues if isinstance(item, str) and item.strip()] if isinstance(issues, list) else []
    if compliance_status:
        return {
            "is_compliant": compliance_status in {"compliant", "approved", "pass", "passed"},
            "violations": violations,
        }
    return normalized


def _sanitize_event_context(event_context: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(event_context)
    for key in ("guest_name", "reservation_id"):
        if key in sanitized:
            sanitized[key] = "[REDACTED]"
    return sanitized


def _log_inference_event(
    event_name: str,
    *,
    run_id: UUID | None,
    model_name: str,
    payload: dict[str, Any],
) -> None:
    logger.warning(
        "%s %s",
        event_name,
        json.dumps(
            {
                "run_id": str(run_id) if run_id else None,
                "model_name": model_name,
                "payload": payload,
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        ),
    )
