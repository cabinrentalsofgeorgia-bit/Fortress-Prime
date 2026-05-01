"""BRAIN inference client.

Streams by default per BRAIN-production-validation-2026-04-29.md Phase 7.2.
Non-streaming is reserved for short-output classification (max_tokens <= 1000)
because long-output non-streaming has been observed to time out or truncate
mid-response on the underlying NIM/vLLM stack.

This module is read-only: it does not retry, mutate any sovereign store, or
call Council deliberation paths. Caller decides retry policy.

# Reasoning controls (post-PR #330 probe matrix, 2026-04-30)
The vLLM nemotron_v3 reasoning parser exposes thinking depth via three knobs.
PR #330's empirical probes settled the schema: all three must be placed at
the TOP LEVEL of the request body. The OpenAI-style `extra_body` wrapper is
silently dropped by vLLM's OpenAI-compat server (Probe E ran 2,554 reasoning
tokens against a 2,048 budget when wrapped, vs 1,195 unwrapped — same body
otherwise).

Wired knobs (constructor + per-call):
- ``enable_thinking: bool | None`` — when False, model emits content directly
  with no reasoning trace (mechanical sections, §2/§7 fix).
- ``low_effort: bool | None`` — meaningful only when enable_thinking=True;
  cuts reasoning depth dramatically (§4 stress test: 21,656 → 1,337 chars
  direct, 21,656 → 210 chars via LiteLLM).
- ``thinking_token_budget: int | None`` — top-level field; defensive ceiling.
  PR #330 + Phase 2 stress could not conclusively prove logits-processor
  enforcement on this build (low_effort kept reasoning well under budget),
  so the budget is wired as a defensive ceiling rather than load-bearing.
- ``force_nonempty_content: bool | None`` — Wave 4 parser safety valve.
  When reasoning hits max_tokens without emitting ``</think>``, the
  super_v3_reasoning_parser routes accumulated output to ``content`` rather
  than stranding it in ``reasoning_content``. Cheap insurance, no behavioral
  cost on the success path. Passed via top-level ``chat_template_kwargs``.

Response-shape divergence between paths:
- Direct vLLM: ``message.reasoning`` (and ``delta.reasoning`` in streaming).
- Via LiteLLM: ``message.reasoning_content`` (and ``delta.reasoning_content``
  in streaming).
``last_reasoning`` accumulates whichever field is present.

# Deprecated kwargs
- ``reasoning_effort`` (added in PR #326 Defect 3) — OpenAI-class schema,
  not honored by Nemotron's chat template. LiteLLM's ``drop_params: true``
  silently drops it. Kept for backward compat; logs a one-shot deprecation
  warning when set; NOT injected into the request body.
- ``thinking`` (added in PR #326 Defect 3) — wrong key (chat template uses
  ``enable_thinking``). Kept for backward compat; logs a one-shot deprecation
  warning when set; NOT injected. Callers should switch to ``enable_thinking``.
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

    Reasoning-aware: parses both ``message.reasoning`` (direct vLLM) and
    ``message.reasoning_content`` (via LiteLLM). After a chat() call completes,
    ``client.last_reasoning`` exposes the reasoning trace and
    ``client.last_finish_reason`` exposes the terminating cause (``stop``,
    ``length``, etc.).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 600.0,
        model: str = _DEFAULT_MODEL,
        *,
        # Defect 2 — per-instance default for callers that don't specify max_tokens
        default_max_tokens: int = _DEFAULT_MAX_TOKENS,
        # Phase 2 reasoning controls (PR #330 probe matrix)
        enable_thinking: Optional[bool] = None,
        low_effort: Optional[bool] = None,
        thinking_token_budget: Optional[int] = None,
        # Wave 4 parser safety valve — when reasoning hits max_tokens without
        # emitting </think>, force the parser to land output in `content` rather
        # than stranding it in `reasoning_content`. See super_v3_reasoning_parser.py.
        force_nonempty_content: Optional[bool] = None,
        # Wave 4 sampling override — NVIDIA Nemotron-3-Super calibrates against
        # temperature=1.0, top_p=0.95 across all modes. Per-section policy can
        # override these via SECTION_REASONING_POLICY; default behavior unchanged
        # when not set.
        top_p: Optional[float] = None,
        # Deprecated — kept for backward compat (PR #326)
        reasoning_effort: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> None:
        self.base_url = (base_url or _cfg.brain_base_url).rstrip("/")
        self.timeout = timeout
        self.model = model
        self.default_max_tokens = default_max_tokens
        self.enable_thinking = enable_thinking
        self.low_effort = low_effort
        self.thinking_token_budget = thinking_token_budget
        self.force_nonempty_content = force_nonempty_content
        self.top_p = top_p
        # Deprecated — stored for introspection but never injected into the request
        self.reasoning_effort = reasoning_effort
        self.thinking = thinking
        if reasoning_effort is not None:
            _warn_deprecated_once(
                "BrainClient(reasoning_effort=...) — OpenAI-class schema not honored "
                "by Nemotron; param will not be injected. Use low_effort=True or "
                "thinking_token_budget=N instead."
            )
        if thinking is not None:
            _warn_deprecated_once(
                "BrainClient(thinking=...) — wrong chat-template key; not injected. "
                "Use enable_thinking=... instead."
            )
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
        # Phase 2 per-call overrides
        enable_thinking: Optional[bool] = None,
        low_effort: Optional[bool] = None,
        thinking_token_budget: Optional[int] = None,
        # Wave 4 parser safety valve
        force_nonempty_content: Optional[bool] = None,
        # Wave 4 sampling override — top_p sent at top level; per-call wins over instance default
        top_p: Optional[float] = None,
        # Deprecated — kept for backward compat (PR #326)
        reasoning_effort: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> Union[AsyncIterator[str], dict]:
        """Call BRAIN /v1/chat/completions.

        - stream=True (default): returns an async iterator yielding content chunks.
        - stream=False: returns the parsed response dict; rejects max_tokens > 1000.

        ``max_tokens=None`` resolves to ``self.default_max_tokens``.

        Reasoning-control kwargs (per-call value wins over instance default):
        - ``enable_thinking``       → top-level ``chat_template_kwargs.enable_thinking``
        - ``low_effort``            → top-level ``chat_template_kwargs.low_effort``
        - ``force_nonempty_content`` → top-level ``chat_template_kwargs.force_nonempty_content``
          (Wave 4 parser safety valve — when reasoning hits max_tokens without emitting
          ``</think>``, super_v3_reasoning_parser routes output to ``content`` rather
          than stranding it in ``reasoning_content``)
        - ``thinking_token_budget`` → top-level ``thinking_token_budget`` field
        All four are placed at the top level of the request body (NOT inside
        ``extra_body`` — vLLM silently drops nested fields per PR #330 Probe E).

        Deprecated kwargs (``reasoning_effort``, ``thinking``) emit a one-shot
        warning and are NOT injected into the request body.

        ``transport`` is for tests only (httpx.MockTransport injection).
        """
        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        if not stream and effective_max_tokens > _NONSTREAM_MAX_TOKENS_LIMIT:
            raise BrainClientError(
                "non-streaming long-output forbidden; use stream=True"
            )

        # Resolve effective per-call values (per-call > instance default)
        eff_enable_thinking = (
            enable_thinking if enable_thinking is not None else self.enable_thinking
        )
        eff_low_effort = low_effort if low_effort is not None else self.low_effort
        eff_thinking_token_budget = (
            thinking_token_budget
            if thinking_token_budget is not None
            else self.thinking_token_budget
        )
        eff_force_nonempty_content = (
            force_nonempty_content
            if force_nonempty_content is not None
            else self.force_nonempty_content
        )
        eff_top_p = top_p if top_p is not None else self.top_p

        # Deprecation warnings for per-call use
        if reasoning_effort is not None:
            _warn_deprecated_once(
                "BrainClient.chat(reasoning_effort=...) deprecated — not injected."
            )
        if thinking is not None:
            _warn_deprecated_once(
                "BrainClient.chat(thinking=...) deprecated — use enable_thinking=..."
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": effective_max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        # Top-level chat_template_kwargs — only includes keys actually set
        chat_template_kwargs: dict[str, Any] = {}
        if eff_enable_thinking is not None:
            chat_template_kwargs["enable_thinking"] = eff_enable_thinking
        if eff_low_effort is not None:
            chat_template_kwargs["low_effort"] = eff_low_effort
        if eff_force_nonempty_content is not None:
            chat_template_kwargs["force_nonempty_content"] = eff_force_nonempty_content
        if chat_template_kwargs:
            payload["chat_template_kwargs"] = chat_template_kwargs

        # Top-level thinking_token_budget (NOT nested in extra_body or chat_template_kwargs)
        if eff_thinking_token_budget is not None:
            payload["thinking_token_budget"] = eff_thinking_token_budget

        # Top-level top_p (NVIDIA-recommended sampling for Nemotron-3-Super = top_p=0.95)
        if eff_top_p is not None:
            payload["top_p"] = eff_top_p

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
                # Capture reasoning + finish_reason for caller introspection.
                # Direct vLLM emits `message.reasoning`; via LiteLLM it's
                # `message.reasoning_content`. Read both, prefer reasoning_content
                # since that's what production callers go through (LiteLLM proxy).
                try:
                    choice0 = data["choices"][0]
                    msg = choice0.get("message", {}) or {}
                    self.last_reasoning = (
                        msg.get("reasoning_content") or msg.get("reasoning") or ""
                    )
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
        """Yield ``delta.content`` chunks. Accumulate ``delta.reasoning`` and
        ``delta.reasoning_content`` chunks to ``self.last_reasoning`` (the
        former is direct vLLM's wire format; the latter is LiteLLM's). Without
        parsing both, content can appear empty when reasoning fills the budget
        — see Track A (PR #323) for the failure mode.
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
                        # Accumulate reasoning from either field; do NOT yield
                        reasoning_chunk = (
                            delta.get("reasoning_content") or delta.get("reasoning")
                        )
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


_deprecation_warned: set[str] = set()


def _warn_deprecated_once(message: str) -> None:
    """Log a deprecation warning once per process per message."""
    if message in _deprecation_warned:
        return
    _deprecation_warned.add(message)
    logger.warning("brain_client_deprecated  %s", message)
