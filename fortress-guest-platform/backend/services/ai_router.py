"""
Resilient AI router for legal/agent services.

Routes to local Ollama first (sovereign default), then optionally OpenAI
when credentials are available.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import structlog

from backend.core.config import settings
from backend.services.openshell_audit import record_audit_event
from backend.services.privacy_router import sanitize_for_cloud
from backend.services.swarm_service import submit_chat_completion

_capture_log = structlog.get_logger(service="ai_router.capture")


async def _capture_interaction(
    *,
    source_module: str,
    prompt: str,
    response: str,
    model_label: str,
    db: Any | None = None,
) -> None:
    """
    Write a frontier-model interaction to llm_training_captures.

    Fire-and-forget — never raises.  Called after every successful cloud
    fallback so the nightly fine-tune job has fresh teacher data.
    The table is bootstrapped by nightly_distillation_exporter on first run.
    """
    try:
        from sqlalchemy import text
        from backend.core.database import AsyncSessionLocal

        async def _insert() -> None:
            async with AsyncSessionLocal() as session:
                await session.execute(text("""
                    INSERT INTO llm_training_captures
                        (source_module, model_used, user_prompt, assistant_resp, status)
                    VALUES
                        (:module, :model, :prompt, :response, 'pending')
                    ON CONFLICT DO NOTHING
                """), {
                    "module":   source_module[:120],
                    "model":    model_label[:120],
                    "prompt":   prompt[:32_000],
                    "response": response[:32_000],
                })
                await session.commit()

        asyncio.create_task(_insert())
    except Exception as exc:
        _capture_log.warning("distillation_capture_failed", error=str(exc)[:200])


@dataclass
class InferenceResult:
    text: str = ""
    source: str = "none"
    breaker_state: str = "closed"
    latency_ms: int = 0
    raw: Optional[Any] = None
    error: Optional[str] = None


def _preferred_ollama_model(task_type: str) -> str:
    if task_type in {"legal", "reasoning", "analysis"}:
        return settings.ollama_deep_model
    return settings.ollama_fast_model


async def _call_ollama(
    *,
    prompt: str,
    system_message: Optional[str],
    model: str,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ((data.get("message") or {}).get("content") or "").strip()


async def _call_openai(
    *,
    prompt: str,
    system_message: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> str:
    response = await submit_chat_completion(
        prompt=prompt,
        model=settings.openai_model,
        system_message=system_message,
        timeout_s=timeout_s,
        extra_payload={
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    choices = response.get("choices") or []
    if not choices:
        return ""
    return (((choices[0] or {}).get("message") or {}).get("content") or "").strip()


async def execute_resilient_inference(
    prompt: str,
    task_type: str,
    system_message: Optional[str] = None,
    max_tokens: int = 256,
    temperature: float = 0.2,
    db: Any = None,
    source_module: Optional[str] = None,
    **kwargs: Any,
) -> InferenceResult:
    request_id = kwargs.get("request_id")
    timeout_s = float(kwargs.get("timeout_s", 45.0))
    start = time.perf_counter()
    errors: list[str] = []

    # 1) Sovereign default: local Ollama
    try:
        text = await _call_ollama(
            prompt=prompt,
            system_message=system_message,
            model=_preferred_ollama_model(task_type),
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )
        result = InferenceResult(
            text=text,
            source="ollama",
            breaker_state="closed",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        await record_audit_event(
            actor_id=None,
            action="ai_inference",
            resource_type="model_route",
            resource_id=task_type,
            purpose=source_module or "resilient_inference",
            redaction_status="not_applicable",
            model_route="local_ollama",
            outcome="success",
            request_id=request_id,
            metadata_json={
                "task_type": task_type,
                "source_module": source_module,
                "latency_ms": result.latency_ms,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            db=db,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ollama:{exc}")

    # 2) Cloud fallback: OpenAI
    try:
        privacy_decision = sanitize_for_cloud({"prompt": prompt, "system_message": system_message or ""})
        safe_prompt = str((privacy_decision.redacted_payload or {}).get("prompt", ""))
        safe_system_message = str((privacy_decision.redacted_payload or {}).get("system_message", ""))
        text = await _call_openai(
            prompt=safe_prompt,
            system_message=safe_system_message,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )
        result = InferenceResult(
            text=text,
            source="openai",
            breaker_state="closed",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        await record_audit_event(
            actor_id=None,
            action="ai_inference",
            resource_type="model_route",
            resource_id=task_type,
            purpose=source_module or "resilient_inference",
            redaction_status=privacy_decision.redaction_status,
            model_route="litellm_gateway_redacted",
            outcome="success",
            request_id=request_id,
            metadata_json={
                "task_type": task_type,
                "source_module": source_module,
                "latency_ms": result.latency_ms,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "redaction_count": privacy_decision.redaction_count,
                "removed_fields": privacy_decision.removed_fields,
            },
            db=db,
        )
        # Capture for nightly distillation flywheel (fire-and-forget)
        await _capture_interaction(
            source_module=source_module or "resilient_inference",
            prompt=safe_prompt,
            response=text,
            model_label=f"godhead/{settings.openai_model}",
            db=db,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openai:{exc}")

    # 3) Deterministic degraded fallback (never throw in call sites)
    result = InferenceResult(
        text=prompt[:400],
        source="fallback",
        breaker_state="open",
        latency_ms=int((time.perf_counter() - start) * 1000),
        error="; ".join(errors)[:500],
    )
    await record_audit_event(
        actor_id=None,
        action="ai_inference",
        resource_type="model_route",
        resource_id=task_type,
        purpose=source_module or "resilient_inference",
        redaction_status="not_applicable",
        model_route="degraded_fallback",
        outcome="error",
        request_id=request_id,
        metadata_json={
            "task_type": task_type,
            "source_module": source_module,
            "latency_ms": result.latency_ms,
            "error": result.error,
        },
        db=db,
    )
    return result

