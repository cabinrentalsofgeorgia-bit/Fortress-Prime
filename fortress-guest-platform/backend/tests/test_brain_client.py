"""Unit tests for backend.services.brain_client.

No real spark-5 connectivity required — all transport is mocked via
httpx.MockTransport.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import pytest

from backend.services.brain_client import BrainClient, BrainClientError


def _ok_nonstream_response(content: str = "ok") -> httpx.Response:
    body = {
        "id": "cmpl-test",
        "object": "chat.completion",
        "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    }
    return httpx.Response(200, json=body)


def _sse_response(chunks: list[str]) -> httpx.Response:
    """Build an SSE byte stream of role + content deltas terminated by [DONE]."""
    lines: list[str] = []
    role_event = {
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
    }
    lines.append(f"data: {json.dumps(role_event)}")
    lines.append("")
    for c in chunks:
        ev = {
            "choices": [{"index": 0, "delta": {"content": c}, "finish_reason": None}]
        }
        lines.append(f"data: {json.dumps(ev)}")
        lines.append("")
    finish_event = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    lines.append(f"data: {json.dumps(finish_event)}")
    lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    body = ("\n".join(lines) + "\n").encode("utf-8")
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/event-stream"},
    )


@pytest.mark.asyncio
async def test_streaming_default():
    """chat() without stream kwarg returns something async-iterable."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _sse_response(["hello"])

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    result = await client.chat(messages=[{"role": "user", "content": "hi"}], transport=transport)

    assert hasattr(result, "__aiter__"), "stream=True (default) should yield an async iterator"
    # drain it so the underlying client/stream closes cleanly
    collected: list[str] = []
    async for chunk in result:  # type: ignore[union-attr]
        collected.append(chunk)
    assert collected == ["hello"]


@pytest.mark.asyncio
async def test_nonstream_short_output_allowed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _ok_nonstream_response("classified=A")

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    result = await client.chat(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=500,
        stream=False,
        transport=transport,
    )

    assert isinstance(result, dict)
    assert result["choices"][0]["message"]["content"] == "classified=A"
    assert result["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_nonstream_long_output_rejected():
    client = BrainClient(base_url="http://mock-brain")
    with pytest.raises(BrainClientError, match="non-streaming long-output forbidden"):
        await client.chat(
            messages=[{"role": "user", "content": "x"}],
            max_tokens=2000,
            stream=False,
        )


@pytest.mark.asyncio
async def test_streaming_chunks_reassemble():
    expected_chunks = ["The ", "procedural ", "posture ", "is ", "..."]

    def handler(_request: httpx.Request) -> httpx.Response:
        return _sse_response(expected_chunks)

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        stream=True,
        transport=transport,
    )

    received: list[str] = []
    async for chunk in iterator:
        received.append(chunk)

    assert received == expected_chunks
    assert "".join(received) == "The procedural posture is ..."


@pytest.mark.asyncio
async def test_timeout_raises_brain_client_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain", timeout=0.1)

    with pytest.raises(BrainClientError, match="timed out"):
        await client.chat(
            messages=[{"role": "user", "content": "x"}],
            max_tokens=500,
            stream=False,
            transport=transport,
        )


@pytest.mark.asyncio
async def test_brain_unreachable_raises_brain_client_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated unreachable")

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")

    with pytest.raises(BrainClientError):
        await client.chat(
            messages=[{"role": "user", "content": "x"}],
            max_tokens=500,
            stream=False,
            transport=transport,
        )


@pytest.mark.asyncio
async def test_streaming_unreachable_raises_brain_client_error():
    """Stream-mode connection failure must also surface as BrainClientError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated unreachable")

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")

    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        stream=True,
        transport=transport,
    )

    with pytest.raises(BrainClientError):
        async for _ in iterator:
            pass


# ── Path X TP=2 frontier compatibility (Track A defects 1/2/3) ─────────────


def _sse_response_with_reasoning(
    reasoning_chunks: list[str],
    content_chunks: list[str],
    finish_reason: str = "stop",
) -> httpx.Response:
    """vLLM nemotron_v3 wire format: reasoning chunks first, then content."""
    lines: list[str] = []
    role_event = {
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
    }
    lines.append(f"data: {json.dumps(role_event)}")
    lines.append("")
    for r in reasoning_chunks:
        ev = {"choices": [{"index": 0, "delta": {"reasoning": r}, "finish_reason": None}]}
        lines.append(f"data: {json.dumps(ev)}")
        lines.append("")
    for c in content_chunks:
        ev = {"choices": [{"index": 0, "delta": {"content": c}, "finish_reason": None}]}
        lines.append(f"data: {json.dumps(ev)}")
        lines.append("")
    finish_event = {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
    lines.append(f"data: {json.dumps(finish_event)}")
    lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    body = ("\n".join(lines) + "\n").encode("utf-8")
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/event-stream"},
    )


def test_default_max_tokens_is_8000():
    """Defect 2 regression guard — module + instance defaults bumped from 4000 to 8000."""
    from backend.services import brain_client as _bc
    assert _bc._DEFAULT_MAX_TOKENS == 8000
    client = BrainClient(base_url="http://mock-brain")
    assert client.default_max_tokens == 8000


def test_constructor_accepts_reasoning_kwargs():
    """Defect 3 — constructor stores reasoning_effort + thinking kwargs."""
    client = BrainClient(
        base_url="http://mock-brain",
        reasoning_effort="high",
        thinking=True,
    )
    assert client.reasoning_effort == "high"
    assert client.thinking is True


@pytest.mark.asyncio
async def test_extra_body_injection_when_reasoning_kwargs_set():
    """Defect 3 — reasoning_effort + thinking land in payload."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _ok_nonstream_response("x")

    transport = httpx.MockTransport(handler)
    client = BrainClient(
        base_url="http://mock-brain",
        reasoning_effort="high",
        thinking=True,
    )
    await client.chat(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=500,
        stream=False,
        transport=transport,
    )
    assert len(captured_payloads) == 1
    body = captured_payloads[0]
    assert body.get("reasoning_effort") == "high"
    assert body.get("chat_template_kwargs") == {"thinking": True}


@pytest.mark.asyncio
async def test_extra_body_omitted_when_reasoning_kwargs_unset():
    """Defect 3 — when neither constructor nor per-call sets the flags, they are NOT in payload."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _ok_nonstream_response("x")

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")  # no reasoning kwargs
    await client.chat(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=500,
        stream=False,
        transport=transport,
    )
    body = captured_payloads[0]
    assert "reasoning_effort" not in body
    assert "chat_template_kwargs" not in body


@pytest.mark.asyncio
async def test_per_call_reasoning_kwargs_override_constructor():
    """Defect 3 — per-call kwargs win over constructor defaults."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _ok_nonstream_response("x")

    transport = httpx.MockTransport(handler)
    client = BrainClient(
        base_url="http://mock-brain",
        reasoning_effort="high",
        thinking=True,
    )
    await client.chat(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=500,
        stream=False,
        transport=transport,
        reasoning_effort="low",
        thinking=False,
    )
    body = captured_payloads[0]
    assert body["reasoning_effort"] == "low"
    assert body["chat_template_kwargs"]["thinking"] is False


@pytest.mark.asyncio
async def test_stream_parses_delta_reasoning_separately():
    """Defect 1 — reasoning chunks accumulate to client.last_reasoning, not yielded as content."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _sse_response_with_reasoning(
            reasoning_chunks=["We", " need", " to"],
            content_chunks=["## Section", " 4"],
            finish_reason="stop",
        )

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        stream=True,
        transport=transport,
    )

    received: list[str] = []
    async for chunk in iterator:
        received.append(chunk)

    # Backward-compat: only content chunks yielded
    assert received == ["## Section", " 4"]
    assert "".join(received) == "## Section 4"
    # Defect 1 fix: reasoning accumulated in side channel
    assert client.last_reasoning == "We need to"
    assert client.last_finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_pre_existing_consumer_pattern_unchanged():
    """Defect 1 — backward-compat sanity: existing `response += chunk` accumulator
    still produces content-only string with no reasoning bleed-through."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _sse_response_with_reasoning(
            reasoning_chunks=["First, I'll", " analyze"],  # first-person prose
            content_chunks=["Defense theory: ", "encroachment ", "voids ", "performance."],
            finish_reason="stop",
        )

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        stream=True,
        transport=transport,
    )
    response = ""
    async for chunk in iterator:
        response += chunk
    assert response == "Defense theory: encroachment voids performance."
    # Critically: no first-person reasoning in the content stream
    assert "I'll" not in response
    assert "First" not in response


@pytest.mark.asyncio
async def test_oneshot_captures_reasoning_and_finish_reason():
    """Defect 1 — non-streaming path also exposes reasoning + finish_reason via instance attrs."""
    body = {
        "id": "cmpl-test",
        "object": "chat.completion",
        "model": "nemotron-3-super",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "## Defenses",
                    "reasoning": "Think through each defense theory under Georgia law.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    result = await client.chat(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=500,
        stream=False,
        transport=transport,
    )
    assert isinstance(result, dict)
    assert result["choices"][0]["message"]["content"] == "## Defenses"
    assert client.last_reasoning == "Think through each defense theory under Georgia law."
    assert client.last_finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_resolves_default_max_tokens_when_caller_passes_none():
    """Defect 2 — max_tokens=None resolves to client.default_max_tokens (8000)."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _sse_response_with_reasoning(
            reasoning_chunks=[],
            content_chunks=["ok"],
        )

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain")
    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        # max_tokens omitted → falls back to default_max_tokens
        transport=transport,
    )
    async for _ in iterator:
        pass
    assert captured_payloads[0]["max_tokens"] == 8000


@pytest.mark.asyncio
async def test_constructor_default_max_tokens_override():
    """Defect 2 — constructor can override the per-instance default."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _sse_response_with_reasoning(reasoning_chunks=[], content_chunks=["ok"])

    transport = httpx.MockTransport(handler)
    client = BrainClient(base_url="http://mock-brain", default_max_tokens=12000)
    iterator: AsyncIterator[str] = await client.chat(  # type: ignore[assignment]
        messages=[{"role": "user", "content": "x"}],
        transport=transport,
    )
    async for _ in iterator:
        pass
    assert captured_payloads[0]["max_tokens"] == 12000
