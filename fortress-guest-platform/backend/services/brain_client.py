"""BRAIN inference client.

Streams by default per BRAIN-production-validation-2026-04-29.md Phase 7.2.
Non-streaming is reserved for short-output classification (max_tokens <= 1000)
because long-output non-streaming has been observed to time out or truncate
mid-response on the underlying NIM/vLLM stack.

This module is read-only: it does not retry, mutate any sovereign store, or
call Council deliberation paths. Caller decides retry policy.
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


class BrainClientError(RuntimeError):
    """Any failure interacting with BRAIN — transport, protocol, or contract."""


class BrainClient:
    """Async OpenAI-compatible client for the BRAIN inference service.

    Defaults to streaming; non-streaming is allowed only for short outputs.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 600.0,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self.base_url = (base_url or _cfg.brain_base_url).rstrip("/")
        self.timeout = timeout
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 4000,
        temperature: float = 0.0,
        stream: bool = True,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> Union[AsyncIterator[str], dict]:
        """Call BRAIN /v1/chat/completions.

        - stream=True (default): returns an async iterator yielding content chunks.
        - stream=False: returns the parsed response dict; rejects max_tokens > 1000.

        ``transport`` is for tests only (httpx.MockTransport injection).
        """
        if not stream and max_tokens > _NONSTREAM_MAX_TOKENS_LIMIT:
            raise BrainClientError(
                "non-streaming long-output forbidden; use stream=True"
            )

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

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
                return resp.json()
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
                        delta = choices[0].get("delta") or {}
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
