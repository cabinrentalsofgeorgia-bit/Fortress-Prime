"""Tests for the Council consumer cutover (ADR-003 Phase 1 follow-up, 2026-04-29).

After PR #285 cut LiteLLM gateway routes cloud → spark-5 NIM, the four sovereign
aliases (`legal-reasoning`, `legal-classification`, `legal-summarization`,
`legal-brain`) became available. This file pins the consumer cutover: the
default model assignments in `legal_council.py` must use those aliases (not
the old cloud aliases like `claude-sonnet-4-6` / `gpt-4o`), and the streaming
path must be active for sovereign calls.

Tests run without spark-5 connectivity — all transport is mocked via
httpx.MockTransport.
"""

from __future__ import annotations

import ast
import json
from importlib import reload
from pathlib import Path

import httpx
import pytest


_SOVEREIGN_ALIASES = {
    "legal-reasoning",
    "legal-classification",
    "legal-summarization",
    "legal-brain",
}

_FORBIDDEN_CLOUD_DEFAULTS = {
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "gpt-4o",
    "grok-4",
    "deepseek-chat",
    "deepseek-reasoner",
    "gemini-2.5-pro",
}

_LEGAL_COUNCIL_PATH = (
    Path(__file__).resolve().parents[1] / "services" / "legal_council.py"
)

_TRACKED_MODEL_CONSTANTS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_OPUS_MODEL",
    "OPENAI_MODEL",
    "XAI_MODEL",
    "XAI_MODEL_FLAGSHIP",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_REASONER_MODEL",
    "GEMINI_MODEL",
)


def _parse_module_defaults() -> dict[str, str]:
    """Parse `legal_council.py` source statically and extract the second
    argument of each `os.getenv("<NAME>", "<DEFAULT>")` call for the tracked
    model constants. Static parse avoids load_dotenv interference: the
    rollback contract permits a runtime override via .env, but the in-code
    default that the cutover establishes is what we want to pin here."""
    tree = ast.parse(_LEGAL_COUNCIL_PATH.read_text(encoding="utf-8"))
    defaults: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id not in _TRACKED_MODEL_CONSTANTS:
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        # os.getenv("KEY", "DEFAULT") — match the second argument
        if len(call.args) < 2:
            continue
        default_arg = call.args[1]
        if isinstance(default_arg, ast.Constant) and isinstance(default_arg.value, str):
            defaults[target.id] = default_arg.value

    return defaults


def test_seat_routing_source_defaults_are_sovereign():
    """Every in-code default for the tracked model constants must resolve to
    one of the four sovereign aliases. Catches regression of any seat
    reverting to a cloud alias in source."""
    defaults = _parse_module_defaults()
    assert set(defaults.keys()) == set(_TRACKED_MODEL_CONSTANTS), (
        f"Static parse missed constants: expected {set(_TRACKED_MODEL_CONSTANTS)}, "
        f"got {set(defaults.keys())}"
    )
    for name, value in defaults.items():
        assert value in _SOVEREIGN_ALIASES, (
            f"{name} default ({value!r}) is not a sovereign alias. "
            f"Allowed: {sorted(_SOVEREIGN_ALIASES)}"
        )


def test_no_cloud_aliases_in_source_defaults():
    """Stronger pin: none of the historical cloud aliases may appear as
    in-code default values for the model constants. Operator can still
    flip a seat back to cloud via env var (rollback contract), but the
    source default must be sovereign."""
    defaults = _parse_module_defaults()
    for name, value in defaults.items():
        assert value not in _FORBIDDEN_CLOUD_DEFAULTS, (
            f"{name} = {value!r} is a cloud alias in source. After the "
            f"ADR-003 Phase 1 consumer cutover the in-code default must be "
            f"sovereign; cloud routing is via env-var override only."
        )


def test_env_override_still_wins(monkeypatch):
    """Rollback contract: setting ANTHROPIC_MODEL via env var must override
    the sovereign default. This is how the operator one-line-reverts to
    cloud if BRAIN goes down."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    from backend.services import legal_council as lc
    reloaded = reload(lc)
    assert reloaded.ANTHROPIC_MODEL == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_call_llm_streams_for_sovereign_alias(monkeypatch):
    """When `_call_llm` runs against the LiteLLM base URL with a `legal-*`
    model alias, it must POST `stream: true` to the gateway and reassemble
    chunks via SSE. This is the streaming-default discipline from the
    Phase A5 BrainClient (PR #280)."""
    from backend.services import legal_council as lc
    reload(lc)

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        sse = (
            'data: {"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{"content":"sovereign "},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            content=sse.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)

    # Patch httpx.AsyncClient so _call_llm uses the MockTransport.
    real_async_client = httpx.AsyncClient

    class _PatchedClient(real_async_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(lc.httpx, "AsyncClient", _PatchedClient)

    content, model = await lc._call_llm(
        "system prompt",
        "user prompt",
        model="legal-reasoning",
        base_url=lc._LITELLM_BASE,
        api_key="dummy",
    )
    assert content == "sovereign answer"
    assert model == "legal-reasoning"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "legal-reasoning"
    assert captured["url"].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_call_llm_does_not_stream_for_local_ollama(monkeypatch):
    """The streaming path is gated to LiteLLM + sovereign aliases. Local
    Ollama / vLLM fallback callers must keep the non-streaming path so the
    existing fallback chain semantics are preserved."""
    from backend.services import legal_council as lc
    reload(lc)

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        body = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ollama answer"},
                    "finish_reason": "stop",
                }
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    real_async_client = httpx.AsyncClient

    class _PatchedClient(real_async_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(lc.httpx, "AsyncClient", _PatchedClient)

    content, model = await lc._call_llm(
        "system",
        "user",
        model="qwen2.5:7b",
        base_url=lc.SPARK2_URL,
    )
    # Sovereign-alias path is the only path that should send `stream: true`.
    assert "stream" not in captured["body"], (
        "Local Ollama path must not enter the streaming branch; "
        f"captured body: {captured['body']!r}"
    )
    assert content == "ollama answer"
