"""
Swarm chat-completions client routed through the local DGX gateway.
"""
from __future__ import annotations

import re
from typing import Any

from openai import AsyncOpenAI

from backend.core.config import settings


def _normalize_openai_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    if re.search(r"/v\d+$", value):
        return value
    return f"{value}/v1"


DGX_GATEWAY_BASE_URL = _normalize_openai_base_url(settings.dgx_inference_url)
DGX_GATEWAY_API_KEY = (
    str(settings.dgx_inference_api_key or "").strip()
    or str(settings.litellm_master_key or "").strip()
    or "fortress-local-gateway"
)


async def submit_chat_completion(
    *,
    prompt: str,
    model: str,
    system_message: str | None = None,
    timeout_s: float = 60.0,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})
    return await submit_message_completion(
        messages=messages,
        model=model,
        timeout_s=timeout_s,
        extra_payload=extra_payload,
    )


async def submit_message_completion(
    *,
    messages: list[dict[str, Any]],
    model: str,
    timeout_s: float = 60.0,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not DGX_GATEWAY_BASE_URL:
        raise RuntimeError("DGX_INFERENCE_URL is not configured for swarm gateway routing.")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if extra_payload:
        payload.update(extra_payload)

    client = AsyncOpenAI(
        base_url=DGX_GATEWAY_BASE_URL,
        api_key=DGX_GATEWAY_API_KEY,
        timeout=timeout_s,
    )
    try:
        response = await client.chat.completions.create(**payload)
        return response.model_dump(mode="json")
    finally:
        await client.close()
