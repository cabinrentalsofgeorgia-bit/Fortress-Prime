"""Tests for the COUNCIL_FRONTIER_PROVIDERS_ENABLED degraded-mode safeguard.

Background: when an upstream provider's API key is missing or stale at the
LiteLLM gateway, every seat using that provider returns 4xx. legal_council
silently falls back to local Ollama (qwen2.5:7b) and the resulting opinions
land in llm_training_captures looking like frontier consensus. The gating
flag lets operators restrict deliberation to a known-good provider subset
until upstream keys are fixed, and explicitly *skips* disabled seats rather
than letting them fall back.
"""

from __future__ import annotations

from typing import Any, List

import run  # noqa: F401  # Install runtime import fallback used in production launch.

import pytest

from backend.services import legal_council


def _build_persona(seat: int, name: str = "Test Persona") -> legal_council.LegalPersona:
    return legal_council.LegalPersona(
        name=name,
        slug=f"persona-seat-{seat}",
        seat=seat,
        archetype="test",
        domain="legal",
        god_head_domain="legal",
        worldview="Test worldview.",
        bias=["Test bias."],
        focus_areas=["Test focus."],
        trigger_events=["test trigger"],
        godhead_prompt=f"You are persona at seat {seat}.",
        vector_collection="legal_library",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Allowlist parser
# ─────────────────────────────────────────────────────────────────────────────


def test_default_enabled_providers_is_anthropic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", raising=False)
    enabled = legal_council._get_enabled_frontier_providers()
    assert enabled == frozenset({"anthropic"})


def test_enabled_providers_parses_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic, openai ,xai")
    enabled = legal_council._get_enabled_frontier_providers()
    assert enabled == frozenset({"anthropic", "openai", "xai"})


def test_google_alias_normalizes_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic,google")
    enabled = legal_council._get_enabled_frontier_providers()
    assert enabled == frozenset({"anthropic", "gemini"})


def test_all_token_enables_every_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "all")
    enabled = legal_council._get_enabled_frontier_providers()
    for seat in range(1, 10):
        assert legal_council._seat_frontier_provider_enabled(seat, enabled), (
            f"seat {seat} should be enabled when allowlist is 'all'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Per-seat gating — given the live SEAT_ROUTING (seats 1, 5 = ANTHROPIC,
# seat 9 = ANTHROPIC_OPUS, all of which normalize to "anthropic")
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "enabled_csv,expected_active_seats",
    [
        ("anthropic",                  {1, 5, 9}),
        ("openai",                     {2, 6}),
        ("xai",                        {3, 7}),
        ("deepseek",                   {4, 8}),
        ("anthropic,openai",           {1, 2, 5, 6, 9}),
        ("anthropic,openai,xai,deepseek", {1, 2, 3, 4, 5, 6, 7, 8, 9}),
        ("all",                        {1, 2, 3, 4, 5, 6, 7, 8, 9}),
    ],
)
def test_seat_gating_matches_seat_routing(
    monkeypatch: pytest.MonkeyPatch, enabled_csv: str, expected_active_seats: set[int],
) -> None:
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", enabled_csv)
    enabled = legal_council._get_enabled_frontier_providers()
    active = {
        seat for seat in legal_council.SEAT_ROUTING
        if legal_council._seat_frontier_provider_enabled(seat, enabled)
    }
    assert active == expected_active_seats


# ─────────────────────────────────────────────────────────────────────────────
# Deliberation-level behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_council_skips_disabled_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Personas whose seat routes to a disabled provider are filtered out
    of the deliberation entirely — they never reach analyze_with_persona."""
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic")

    personas = [_build_persona(seat) for seat in range(1, 10)]
    monkeypatch.setattr(
        legal_council.LegalPersona, "load_all", classmethod(lambda cls: list(personas)),
    )

    invoked_seats: List[int] = []

    async def fake_analyze(persona, *args, **kwargs):
        invoked_seats.append(persona.seat)
        return legal_council._make_error_opinion(persona, "stub", 0.0)

    monkeypatch.setattr(legal_council, "analyze_with_persona", fake_analyze)
    monkeypatch.setattr(legal_council, "freeze_context", _stub_freeze_context)
    monkeypatch.setattr(legal_council, "freeze_caselaw_context", _stub_freeze_caselaw_context)

    events: List[dict[str, Any]] = []

    async def progress_callback(evt: dict[str, Any]) -> None:
        events.append(evt)

    await legal_council.run_council_deliberation(
        session_id="test-skip-disabled",
        case_brief="Smoke test brief.",
        progress_callback=progress_callback,
    )

    # Only seats 1, 5, 9 (ANTHROPIC / ANTHROPIC_OPUS) should have been invoked.
    assert set(invoked_seats) == {1, 5, 9}, (
        f"expected only Anthropic-provider seats to fan out, got {sorted(invoked_seats)}"
    )

    skipped_evt = next((e for e in events if e.get("type") == "seats_skipped"), None)
    assert skipped_evt is not None, "expected a seats_skipped progress event"
    assert skipped_evt["skipped_count"] == 6
    assert skipped_evt["active_count"] == 3
    assert skipped_evt["enabled_providers"] == ["anthropic"]


@pytest.mark.asyncio
async def test_council_does_not_fallback_to_local_for_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled-provider seat must not reach _call_llm at all — neither
    the primary frontier path nor the HYDRA/Ollama fallback path. Filtering
    happens before any per-seat LLM invocation."""
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic")

    personas = [_build_persona(seat) for seat in range(1, 10)]
    monkeypatch.setattr(
        legal_council.LegalPersona, "load_all", classmethod(lambda cls: list(personas)),
    )

    seen_models: List[str] = []
    seen_base_urls: List[str] = []

    async def fake_call_llm(
        system_prompt: str, user_prompt: str,
        model: str = "", base_url: str = "", api_key: str = "",
        temperature: float = 0.3, max_tokens: int = 4096,
    ) -> tuple[str, str]:
        seen_models.append(model)
        seen_base_urls.append(base_url)
        return ('{"signal":"NEUTRAL","conviction":0.5,"reasoning":"stub",'
                '"defense_arguments":[],"risk_factors":[],"recommended_actions":[]}',
                model or "fake-model")

    monkeypatch.setattr(legal_council, "_call_llm", fake_call_llm)
    monkeypatch.setattr(legal_council, "ALLOW_CLOUD_LLM", True)
    monkeypatch.setattr(legal_council, "freeze_context", _stub_freeze_context)
    monkeypatch.setattr(legal_council, "freeze_caselaw_context", _stub_freeze_caselaw_context)

    await legal_council.run_council_deliberation(
        session_id="test-no-fallback",
        case_brief="Smoke test brief.",
    )

    # No call from a disabled-provider seat should reach _call_llm. The
    # fallback chain in _call_llm would route disabled providers to HYDRA
    # if they ever got there, so the absence of HYDRA URLs here is the
    # actual guarantee we care about.
    forbidden_urls = {
        legal_council.HYDRA_120B_URL,
        legal_council.HYDRA_32B_URL,
        legal_council.SWARM_URL,
        legal_council.SPARK2_URL,
        legal_council.SPARK_LOCAL_URL,
        legal_council.OPENAI_BASE_URL,
        legal_council.XAI_BASE_URL,
        legal_council.DEEPSEEK_BASE_URL,
        legal_council.GEMINI_BASE_URL,
    } - {legal_council.ANTHROPIC_PROXY}
    leaked = set(seen_base_urls) & forbidden_urls
    assert not leaked, f"disabled providers leaked into _call_llm via {leaked}"


@pytest.mark.asyncio
async def test_anthropic_only_deliberation_completes_with_3_seats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end happy path for the degraded-mode floor.

    Note: the user-facing description originally said '2 seats' (Sonnet,
    Opus). The live SEAT_ROUTING actually maps seats 1, 5, 9 to Anthropic
    (Sonnet, Sonnet, Opus) — three seats running two distinct models.
    This test asserts what the deliberation actually does so the count
    discrepancy is visible to anyone editing SEAT_ROUTING in the future.
    """
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic")

    personas = [_build_persona(seat) for seat in range(1, 10)]
    monkeypatch.setattr(
        legal_council.LegalPersona, "load_all", classmethod(lambda cls: list(personas)),
    )

    completed_seats: List[int] = []

    async def fake_analyze(persona, *args, **kwargs):
        completed_seats.append(persona.seat)
        return legal_council._make_error_opinion(persona, "stub", 0.0)

    monkeypatch.setattr(legal_council, "analyze_with_persona", fake_analyze)
    monkeypatch.setattr(legal_council, "freeze_context", _stub_freeze_context)
    monkeypatch.setattr(legal_council, "freeze_caselaw_context", _stub_freeze_caselaw_context)

    events: List[dict[str, Any]] = []

    async def progress_callback(evt: dict[str, Any]) -> None:
        events.append(evt)

    await legal_council.run_council_deliberation(
        session_id="test-anthropic-only",
        case_brief="Smoke test brief.",
        progress_callback=progress_callback,
    )

    assert sorted(completed_seats) == [1, 5, 9], (
        "Anthropic-only allowlist should fan out exactly to seats 1 (Sonnet), "
        f"5 (Sonnet), 9 (Opus); got {sorted(completed_seats)}"
    )

    error_evt = next((e for e in events if e.get("type") == "error"), None)
    assert error_evt is None, f"unexpected error event: {error_evt!r}"


@pytest.mark.asyncio
async def test_council_emits_error_when_allowlist_excludes_every_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty active set is a hard error, not a silent zero-seat deliberation."""
    monkeypatch.setenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "")

    personas = [_build_persona(seat) for seat in range(1, 10)]
    monkeypatch.setattr(
        legal_council.LegalPersona, "load_all", classmethod(lambda cls: list(personas)),
    )

    async def fake_analyze(persona, *args, **kwargs):
        pytest.fail("no seat should be invoked when allowlist excludes everything")

    monkeypatch.setattr(legal_council, "analyze_with_persona", fake_analyze)
    monkeypatch.setattr(legal_council, "freeze_context", _stub_freeze_context)
    monkeypatch.setattr(legal_council, "freeze_caselaw_context", _stub_freeze_caselaw_context)

    events: List[dict[str, Any]] = []

    async def progress_callback(evt: dict[str, Any]) -> None:
        events.append(evt)

    await legal_council.run_council_deliberation(
        session_id="test-all-disabled",
        case_brief="Smoke test brief.",
        progress_callback=progress_callback,
    )

    error_evt = next((e for e in events if e.get("type") == "error"), None)
    assert error_evt is not None
    assert "COUNCIL_FRONTIER_PROVIDERS_ENABLED" in error_evt["message"]


# ─────────────────────────────────────────────────────────────────────────────
# Stubs
# ─────────────────────────────────────────────────────────────────────────────


async def _stub_freeze_context(case_brief: str, top_k: int = 20, case_slug=None):
    return [], []


async def _stub_freeze_caselaw_context(case_brief: str, top_k: int = 8):
    return [], []
