"""
Resilient AI router for legal/agent services.

Routes to local Ollama first (sovereign default), then optionally OpenAI
when credentials are available.

Phase 2.5: replaces hardcoded ollama_base_url with model_registry which
health-probes all cluster nodes and routes to the healthiest endpoint for
the requested model. On NoHealthyEndpoint, falls through to cloud.

Phase 4c: adds optional distilled-adapter tier (tier 1.5) between Ollama
and OpenAI. Controlled by SOVEREIGN_DISTILL_ADAPTER_PCT (default 0 = off).
Only active when PROMOTED_CANDIDATE sentinel file exists. Legal/privileged
modules are blocked from the adapter tier regardless of PCT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from backend.services.model_registry import NoHealthyEndpoint, registry as _model_registry

from backend.core.config import settings
from backend.services.openshell_audit import record_audit_event
from backend.services.privacy_router import sanitize_for_cloud
from backend.services.swarm_service import submit_chat_completion

_capture_log = structlog.get_logger(service="ai_router.capture")
_adapter_log  = logging.getLogger("ai_router.adapter")

# ---------------------------------------------------------------------------
# Phase 4c — Distilled adapter routing config
# ---------------------------------------------------------------------------
_ADAPTER_PCT  = int(os.getenv("SOVEREIGN_DISTILL_ADAPTER_PCT",  "0"))   # 0 = off
_ADAPTER_URL  = os.getenv("SOVEREIGN_DISTILL_ADAPTER_URL",       "http://127.0.0.1:8100/v1")
_ADAPTER_DIR  = Path(os.getenv("FINETUNE_ADAPTER_DIR",           "/mnt/fortress_nas/finetune-artifacts"))
_SENTINEL     = _ADAPTER_DIR / "PROMOTED_CANDIDATE"

# Source modules that must NEVER be routed to the distilled adapter.
# The adapter was trained on VRS/hospitality data only.
# Legal and privileged modules must stay on frontier models.
_ADAPTER_BLOCKED_MODULES: frozenset[str] = frozenset({
    "legal_council", "ediscovery_agent", "legal_email_intake",
    "legal_intake", "legal_case_graph", "legal_chronology",
    "legal_deposition_prep", "legal_discovery_engine",
    "legal_agent_orchestrator", "legal_email_intake_api",
})


async def _capture_interaction(
    *,
    source_module: str,
    prompt: str,
    response: str,
    model_label: str,
    db: Any | None = None,
    # Phase 3 retag — v5 tagging schema (all optional, None = pre-retag)
    served_by_endpoint:  Optional[str] = None,
    served_vector_store: Optional[str] = None,
    escalated_from:      Optional[str] = None,
    sovereign_attempt:   Optional[str] = None,
    teacher_endpoint:    Optional[str] = None,
    teacher_model:       Optional[str] = None,
    task_type:           Optional[str] = None,
    judge_decision:      Optional[str] = None,
    judge_reasoning:     Optional[str] = None,
) -> None:
    """
    Write a frontier-model interaction to llm_training_captures.

    Fire-and-forget — never raises.  Called after every successful cloud
    fallback so the nightly fine-tune job has fresh teacher data.
    The table is bootstrapped by nightly_distillation_exporter on first run.
    """
    try:
        import uuid as _uuid
        from sqlalchemy import text
        from backend.core.database import AsyncSessionLocal
        from backend.services.privilege_filter import (
            classify_for_capture,
            check_training_contamination,
            CaptureRoute,
        )

        decision = classify_for_capture(
            prompt=prompt,
            response=response,
            source_module=source_module,
        )

        if decision.route == CaptureRoute.BLOCK:
            _capture_log.info("distillation_capture_blocked reason=%s module=%s",
                              decision.reason, source_module)
            return

        contaminated, contamination_reason = check_training_contamination(prompt, response)
        if contaminated:
            _capture_log.warning(
                "training_contamination_detected reason=%s module=%s — "
                "capture will be written with training_excluded=true",
                contamination_reason, source_module,
            )

        async def _insert() -> None:
            async with AsyncSessionLocal() as session:
                _tag = {
                    "endpoint":    served_by_endpoint[:256]  if served_by_endpoint  else None,
                    "store":       served_vector_store[:64]  if served_vector_store else None,
                    "esc_from":    escalated_from[:256]      if escalated_from       else None,
                    "sov_attempt": sovereign_attempt,
                    "t_endpoint":  teacher_endpoint[:256]    if teacher_endpoint    else None,
                    "t_model":     teacher_model[:128]       if teacher_model       else None,
                    "task":        task_type[:64]            if task_type           else None,
                    "judge_dec":   judge_decision[:16]       if judge_decision      else None,
                    "judge_rsn":   judge_reasoning,
                }
                _capture_id = str(_uuid.uuid4())
                _capture_meta = (
                    json.dumps({
                        "training_excluded": True,
                        "exclusion_reason": contamination_reason,
                    })
                    if contaminated else None
                )
                if decision.route == CaptureRoute.ALLOW:
                    await session.execute(text("""
                        INSERT INTO llm_training_captures
                            (id, source_module, model_used, user_prompt, assistant_resp, status,
                             served_by_endpoint, served_vector_store,
                             escalated_from, sovereign_attempt,
                             teacher_endpoint, teacher_model,
                             task_type, judge_decision, judge_reasoning,
                             capture_metadata)
                        VALUES
                            (CAST(:id AS uuid), :module, :model, :prompt, :response, 'pending',
                             :endpoint, :store,
                             :esc_from, :sov_attempt,
                             :t_endpoint, :t_model,
                             :task, :judge_dec, :judge_rsn,
                             CAST(:capture_meta AS jsonb))
                        ON CONFLICT DO NOTHING
                    """), {"id": _capture_id, "module": source_module[:120], "model": model_label[:120],
                           "prompt": prompt[:32_000], "response": response[:32_000],
                           "capture_meta": _capture_meta,
                           **_tag})
                else:  # RESTRICTED
                    await session.execute(text("""
                        INSERT INTO restricted_captures
                            (source_module, prompt, response,
                             restriction_reason, matched_patterns,
                             served_by_endpoint, served_vector_store,
                             escalated_from, sovereign_attempt,
                             teacher_endpoint, teacher_model,
                             task_type, judge_decision, judge_reasoning)
                        VALUES
                            (:module, :prompt, :response, :reason, :patterns,
                             :endpoint, :store,
                             :esc_from, :sov_attempt,
                             :t_endpoint, :t_model,
                             :task, :judge_dec, :judge_rsn)
                    """), {"module": source_module[:120],
                           "prompt": prompt[:32_000], "response": response[:32_000],
                           "reason": decision.reason[:256],
                           "patterns": list(decision.matched_patterns),
                           **_tag})
                await session.commit()

                # Phase 4e.1: queue for Godhead labeling (fire-and-forget thread)
                try:
                    from backend.services.labeling_pipeline import queue_capture_for_labeling
                    capture_tbl = (
                        "llm_training_captures"
                        if decision.route == CaptureRoute.ALLOW
                        else "restricted_captures"
                    )
                    queue_capture_for_labeling(
                        capture_id=_capture_id,
                        capture_table=capture_tbl,
                        task_type=(task_type or "unknown"),
                        user_prompt=prompt,
                        sovereign_response=response,
                    )
                except Exception:
                    pass  # never block capture on labeling failure

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


_DEEP_TASK_TYPES = {"legal", "reasoning", "analysis"}

# Task types that use the dedicated vrs_fast tier (spark-4 primary, Iron Dome v6).
# All other fast tasks continue to use the 'fast' tier (spark-2/spark-1).
_VRS_FAST_TASK_TYPES = {"vrs_concierge"}

def _preferred_ollama_model(task_type: str) -> str:
    if task_type in _DEEP_TASK_TYPES:
        return settings.ollama_deep_model
    return settings.ollama_fast_model


def _tier_for_task(task_type: str) -> str:
    """Map task_type to model registry tier name."""
    if task_type in _DEEP_TASK_TYPES:
        return "deep"
    if task_type in _VRS_FAST_TASK_TYPES:
        return "vrs_fast"
    return "fast"


def _ollama_base_url_for(model: str, tier: Optional[str] = None) -> str:
    """
    Return Ollama base URL for the given model.

    Phase 2.5: prefers model_registry for health-aware routing.
    Falls back to settings.ollama_base_url if registry has no healthy node
    (registry not loaded, atlas missing, or all nodes down).
    """
    try:
        return _model_registry.get_endpoint_for_model(model, tier=tier)
    except NoHealthyEndpoint as exc:
        import logging as _log
        _log.getLogger("ai_router").warning(
            "model_registry.no_healthy_endpoint model=%s tier=%s — using config fallback: %s",
            model, tier, str(exc)[:120],
        )
        return settings.ollama_base_url
    except Exception as exc:
        import logging as _log
        _log.getLogger("ai_router").warning(
            "model_registry.error model=%s — using config fallback: %s", model, str(exc)[:120]
        )
        return settings.ollama_base_url


async def _call_ollama(
    *,
    prompt: str,
    system_message: Optional[str],
    model: str,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    tier: Optional[str] = None,
) -> tuple[str, str]:
    """Returns (response_text, endpoint_url) so callers can tag served_by_endpoint."""
    base_url = _ollama_base_url_for(model, tier=tier)
    url = f"{base_url.rstrip('/')}/api/chat"
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
        text = ((data.get("message") or {}).get("content") or "").strip()
        return text, base_url


async def _call_openai(
    *,
    prompt: str,
    system_message: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> tuple[str, str]:
    """Returns (response_text, endpoint_url) — endpoint is the LiteLLM gateway."""
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
    text = "" if not choices else (
        (((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    )
    return text, str(settings.litellm_base_url)


def _adapter_eligible(source_module: Optional[str]) -> bool:
    """
    Return True if this request is eligible for the distilled-adapter tier.
    Legal/privileged modules are hard-blocked regardless of PCT setting.
    """
    if _ADAPTER_PCT == 0:
        return False
    if not _SENTINEL.exists():
        return False
    if source_module and source_module in _ADAPTER_BLOCKED_MODULES:
        return False
    if source_module and any(
        source_module.startswith(p) for p in ("legal_", "ediscovery_")
    ):
        return False
    return random.randint(1, 100) <= _ADAPTER_PCT


async def _call_adapter(
    prompt: str,
    system_message: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> tuple[str, str]:
    """
    Call the distilled-adapter vLLM OpenAI-compat endpoint.
    Returns (response_text, adapter_url), or raises on failure (caller falls through).

    The adapter serves model 'crog-distilled' at SOVEREIGN_DISTILL_ADAPTER_URL.
    Adapter path is read from the PROMOTED_CANDIDATE sentinel for audit purposes.
    """
    try:
        sentinel_data = json.loads(_SENTINEL.read_text()) if _SENTINEL.exists() else {}
        adapter_path = sentinel_data.get("adapter_path", "unknown")
    except Exception:
        adapter_path = "unknown"

    messages: list[dict] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{_ADAPTER_URL.rstrip('/')}/chat/completions",
            json={
                "model":       "crog-distilled",
                "messages":    messages,
                "max_tokens":  max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    latency_ms = int((time.perf_counter() - t0) * 1000)
    text = (
        ((data.get("choices") or [{}])[0].get("message") or {})
        .get("content", "")
        .strip()
    )
    _adapter_log.info(
        "adapter_call_ok adapter=%s latency_ms=%d tokens=%d",
        adapter_path, latency_ms,
        (data.get("usage") or {}).get("completion_tokens", 0),
    )
    return text, _ADAPTER_URL


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

    # Phase 4e.2: classify v5 labeling task type (non-blocking, default "generic")
    try:
        from backend.services.task_classifier import classify_task_type as _classify
        label_task_type: str = _classify(
            source_module=source_module or "",
            prompt=prompt,
        )
    except Exception:
        label_task_type = "generic"

    # 1) Sovereign default: local Ollama
    try:
        text, _ollama_endpoint = await _call_ollama(
            prompt=prompt,
            system_message=system_message,
            model=_preferred_ollama_model(task_type),
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
            tier=_tier_for_task(task_type),
        )
        result = InferenceResult(
            text=text,
            source="ollama",
            breaker_state="closed",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        # Phase 4e.3: judge evaluation (JUDGE_ENABLED=false default → zero overhead)
        _judge_decision = _judge_reasoning = None
        try:
            from backend.services.judge_runtime import JUDGE_ENABLED, judge_response as _judge
            if JUDGE_ENABLED:
                _jd = await _judge(label_task_type, prompt, text)
                _judge_decision  = _jd.decision
                _judge_reasoning = _jd.reasoning
                if _jd.decision == "escalate":
                    _capture_log.info("judge_escalated task=%s model=%s latency=%dms",
                                      label_task_type, _jd.judge_model, _jd.latency_ms)
                elif _jd.decision == "uncertain":
                    _capture_log.info("judge_uncertain task=%s model=%s latency=%dms",
                                      label_task_type, _jd.judge_model, _jd.latency_ms)
        except Exception:
            pass  # judge never blocks response

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

        # Pass judge decision to capture (for training signal)
        result._judge_decision  = _judge_decision   # type: ignore[attr-defined]
        result._judge_reasoning = _judge_reasoning  # type: ignore[attr-defined]
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ollama:{exc}")

    # 1.5) Distilled adapter (Phase 4c) — only when PCT > 0 and PROMOTED_CANDIDATE exists
    # Default PCT=0 means this block is never entered today.
    # Legal/privileged source_modules are blocked at _adapter_eligible().
    if _adapter_eligible(source_module):
        try:
            adapter_text, _adapter_endpoint = await _call_adapter(
                prompt=prompt,
                system_message=system_message,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=min(timeout_s, 30.0),  # tighter timeout — don't delay cloud fallback
            )
            if adapter_text:
                result = InferenceResult(
                    text=adapter_text,
                    source="distilled_adapter",
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
                    model_route="distilled_adapter",
                    outcome="success",
                    request_id=request_id,
                    metadata_json={
                        "task_type": task_type,
                        "source_module": source_module,
                        "latency_ms": result.latency_ms,
                        "adapter_pct": _ADAPTER_PCT,
                    },
                    db=db,
                )
                return result
        except Exception as exc:  # noqa: BLE001
            _adapter_log.warning("adapter_call_failed error=%s — falling through", str(exc)[:200])
            errors.append(f"adapter:{exc}")

    # 2) Cloud fallback: OpenAI
    try:
        privacy_decision = sanitize_for_cloud({"prompt": prompt, "system_message": system_message or ""})
        safe_prompt = str((privacy_decision.redacted_payload or {}).get("prompt", ""))
        safe_system_message = str((privacy_decision.redacted_payload or {}).get("system_message", ""))
        text, _cloud_endpoint = await _call_openai(
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
        # served_by_endpoint = actual cloud endpoint returned by _call_openai
        # Extract judge decision from sovereign result if it ran before fallback
        _prev_judge_dec = getattr(result, "_judge_decision",  None)
        _prev_judge_rsn = getattr(result, "_judge_reasoning", None)
        await _capture_interaction(
            source_module=source_module or "resilient_inference",
            prompt=safe_prompt,
            response=text,
            model_label=f"godhead/{settings.openai_model}",
            db=db,
            served_by_endpoint=_cloud_endpoint,
            served_vector_store=None,  # RAG integration Phase 5a
            task_type=label_task_type,
            judge_decision=_prev_judge_dec,
            judge_reasoning=_prev_judge_rsn,
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

