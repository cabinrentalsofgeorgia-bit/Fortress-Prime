"""
Resilient AI router for legal/agent services.

Routes to local Ollama first (sovereign default), then optionally OpenAI
when credentials are available.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from backend.core.config import settings


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
    if not settings.openai_api_key:
        raise RuntimeError("openai_api_key not configured")

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.openai_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
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
    _ = (db, source_module, kwargs)
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
        return InferenceResult(
            text=text,
            source="ollama",
            breaker_state="closed",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ollama:{exc}")

    # 2) Cloud fallback: OpenAI
    try:
        text = await _call_openai(
            prompt=prompt,
            system_message=system_message,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )
        return InferenceResult(
            text=text,
            source="openai",
            breaker_state="closed",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openai:{exc}")

    # 3) Deterministic degraded fallback (never throw in call sites)
    return InferenceResult(
        text=prompt[:400],
        source="fallback",
        breaker_state="open",
        latency_ms=int((time.perf_counter() - start) * 1000),
        error="; ".join(errors)[:500],
    )

