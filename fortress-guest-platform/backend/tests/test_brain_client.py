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
