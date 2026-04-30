"""BRAIN inference client.

Streams by default per BRAIN-production-validation-2026-04-29.md Phase 7.2.
Non-streaming is reserved for short-output classification (max_tokens <= 1000)
because long-output non-streaming has been observed to time out or truncate
mid-response on the underlying NIM/vLLM stack.

This module is read-only: it does not retry, mutate any sovereign store, or
call Council deliberation paths. Caller decides retry policy.

# Phase B BrainClient TP=2 frontier compatibility (Path X, 2026-04-30)
Following Track A (PR #323) the client now handles vLLM's nemotron_v3
reasoning parser wire format:
- Stream parses `delta.reasoning` chunks alongside `delta.content`.
  Reasoning is accumulated to `self.last_reasoning` (and exposed via
  `last_finish_reason`); content is yielded as before, so existing
  consumers continue to work unchanged.
- `default_max_tokens` constructor kwarg (default 8000) raises the
  per-call max_tokens floor when callers don't specify, leaving room for
  the reasoning trace to complete before content emission begins.
- `reasoning_effort` and `thinking` kwargs (constructor + per-call) inject
  into the request body's `extra_body` / `chat_template_kwargs`, mirroring
  the per-alias profile config established by Phase 9 LiteLLM alias surgery.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Optional, Union

import httpx

from backend.core.config import settings as _cfg

logger = logging.getLogger(__name__)


_NONSTREAM_MAX_TOKENS_LIMIT = 1000
_DEFAULT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8"
_DEFAULT_MAX_TOKENS = 8000  # was 4000 (chat default) / 2000 (synthesizer cap) — see Track A finding


class BrainClientError(RuntimeError):
    """Any failure interacting with BRAIN — transport, protocol, or contract."""


class BrainClient:
    """Async OpenAI-compatible client for the BRAIN inference service.

    Defaults to streaming; non-streaming is allowed only for short outputs.

    Reasoning-aware: handles vLLM nemotron_v3 reasoning parser wire format.
    After a chat() call completes, `client.last_reasoning` exposes the
    reasoning trace and `client.last_finish_reason` exposes the terminating
    cause (`stop`, `length`, etc.) for both streaming and non-streaming paths.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 600.0,
        model: str = _DEFAULT_MODEL,
        *,
        # Defect 2 — per-instance default for callers that don't specify max_tokens
        default_max_tokens: int = _DEFAULT_MAX_TOKENS,
        # Defect 3 — reasoning controls for vLLM nemotron_v3 parser
        reasoning_effort: Optional[str] = None,  # "low" | "medium" | "high"
        thinking: Optional[bool] = None,          # → chat_template_kwargs.thinking
    ) -> None:
        self.base_url = (base_url or _cfg.brain_base_url).rstrip("/")
        self.timeout = timeout
        self.model = model
        self.default_max_tokens = default_max_tokens
        self.reasoning_effort = reasoning_effort
        self.thinking = thinking
        # Reasoning accumulator + terminating cause exposed after each chat() call
        self.last_reasoning: str = ""
        self.last_finish_reason: Optional[str] = None

    async def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        stream: bool = True,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        *,
        # Per-call overrides for Defect 3 reasoning controls
        reasoning_effort: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> Union[AsyncIterator[str], dict]:
        """Call BRAIN /v1/chat/completions.

        - stream=True (default): returns an async iterator yielding content chunks.
        - stream=False: returns the parsed response dict; rejects max_tokens > 1000.

        ``max_tokens=None`` resolves to ``self.default_max_tokens`` (Defect 2).
        ``reasoning_effort`` / ``thinking`` per-call args fall back to the
        instance defaults set in ``__init__`` (Defect 3); both are injected into
        the request body's ``extra_body`` / ``chat_template_kwargs`` if set.

        ``transport`` is for tests only (httpx.MockTransport injection).
        """
        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        if not stream and effective_max_tokens > _NONSTREAM_MAX_TOKENS_LIMIT:
            raise BrainClientError(
                "non-streaming long-output forbidden; use stream=True"
            )

        effective_reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        )
        effective_thinking = thinking if thinking is not None else self.thinking

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": effective_max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if effective_reasoning_effort is not None:
            payload["reasoning_effort"] = effective_reasoning_effort
        if effective_thinking is not None:
            payload["chat_template_kwargs"] = {"thinking": effective_thinking}

        # Reset per-call accumulators
        self.last_reasoning = ""
        self.last_finish_reason = None

        if stream:
            return self._stream(payload, transport=transport)
        return await self._oneshot(payload, transport=transport)

    async def _oneshot(
        self,
        payload: dict,
        transport: Optional[httpx.AsyncBaseTransport],
    ) -> dict:
        url = f"{self.base_url}/v1/chat/completions"
        started = time.monotonic()
        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if transport is not None:
            client_kwargs["transport"] = transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Capture reasoning + finish_reason for caller introspection (Defect 1, oneshot path)
                try:
                    choice0 = data["choices"][0]
                    msg = choice0.get("message", {}) or {}
                    self.last_reasoning = msg.get("reasoning") or ""
                    self.last_finish_reason = choice0.get("finish_reason")
                except (KeyError, IndexError, TypeError):
                    pass
                return data
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            logger.warning(
                "brain_client_timeout  ttft=n/a  elapsed=%.2fs  max_tokens=%d  stream=False",
                elapsed,
                payload.get("max_tokens", 0),
            )
            raise BrainClientError(f"BRAIN request timed out after {elapsed:.1f}s") from exc
        except httpx.HTTPError as exc:
            raise BrainClientError(f"BRAIN HTTP error: {exc!s}") from exc
        except Exception as exc:
            raise BrainClientError(f"BRAIN call failed: {exc!s}") from exc

    async def _stream(
        self,
        payload: dict,
        transport: Optional[httpx.AsyncBaseTransport],
    ) -> AsyncIterator[str]:
        """Yield ``delta.content`` chunks. Accumulate ``delta.reasoning`` chunks
        to ``self.last_reasoning`` (Defect 1). vLLM nemotron_v3 parser emits
        reasoning chunks first (until the trace completes), then content;
        without parsing both, the content stream may appear empty when the
        reasoning fills the budget — see Track A (PR #323) for the failure mode.
        """
        url = f"{self.base_url}/v1/chat/completions"
        started = time.monotonic()
        ttft: Optional[float] = None
        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if transport is not None:
            client_kwargs["transport"] = transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        finish = choice.get("finish_reason")
                        if finish is not None:
                            self.last_finish_reason = finish
                        delta = choice.get("delta") or {}
                        # Defect 1: accumulate reasoning; do NOT yield (consumers expect content only)
                        reasoning_chunk = delta.get("reasoning")
                        if reasoning_chunk:
                            self.last_reasoning += reasoning_chunk
                        # Yield content as before (backward-compatible)
                        chunk = delta.get("content")
                        if chunk:
                            if ttft is None:
                                ttft = time.monotonic() - started
                            yield chunk
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            logger.warning(
                "brain_client_timeout  ttft=%s  elapsed=%.2fs  max_tokens=%d  stream=True",
                f"{ttft:.2f}s" if ttft is not None else "n/a",
                elapsed,
                payload.get("max_tokens", 0),
            )
            raise BrainClientError(f"BRAIN stream timed out after {elapsed:.1f}s") from exc
        except httpx.HTTPError as exc:
            raise BrainClientError(f"BRAIN HTTP error: {exc!s}") from exc
        except BrainClientError:
            raise
        except Exception as exc:
            raise BrainClientError(f"BRAIN stream failed: {exc!s}") from exc
