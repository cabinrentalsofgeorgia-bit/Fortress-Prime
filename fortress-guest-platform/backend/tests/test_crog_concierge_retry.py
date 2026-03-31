"""Focused tests for CROG concierge parsing fallbacks."""

from __future__ import annotations

import run  # noqa: F401  # Install runtime import fallback used by production launch.

import pytest

from backend.services.crog_concierge_engine import (
    ConciergePersona,
    ConciergeSignal,
    _parse_opinion,
    analyze_with_concierge_persona,
)


def build_persona() -> ConciergePersona:
    return ConciergePersona(
        name="Guest Experience Lead",
        slug="guest-experience-lead",
        seat=1,
        archetype="hospitality-lead",
        domain="hospitality",
        god_head_domain="hospitality",
        worldview="Protect the guest relationship without inventing facts.",
        bias=["Prefer practical service recovery steps."],
        focus_areas=["Guest sentiment", "service recovery"],
        trigger_events=["guest complaint"],
        godhead_prompt="You are the Guest Experience Lead.",
        vector_collection="fgp_knowledge",
    )


def test_parse_opinion_handles_labeled_markdown_response() -> None:
    persona = build_persona()
    raw = """
**Signal:** RESOLVE
**Conviction:** 72%
**Reasoning:** The guest is reporting an unstable core amenity before checkout, so we should acknowledge the issue and move quickly.
**Operational Arguments:**
- Connectivity instability is materially affecting the stay.
- The response should include a concrete follow-up window.
**Risk Factors:**
- Delayed response could trigger a poor review.
**Recommended Actions:**
- Dispatch maintenance to inspect router and ISP status.
- Send a guest-facing update within 15 minutes.
**Departments:** maintenance, guest
""".strip()

    opinion = _parse_opinion(persona, "wifi complaint", raw, "fake-model", 1.2)

    assert opinion.signal == ConciergeSignal.RESOLVE
    assert opinion.conviction == pytest.approx(0.72)
    assert "unstable core amenity" in opinion.reasoning
    assert opinion.operational_arguments == [
        "Connectivity instability is materially affecting the stay.",
        "The response should include a concrete follow-up window.",
    ]
    assert opinion.risk_factors == ["Delayed response could trigger a poor review."]
    assert opinion.recommended_actions == [
        "Dispatch maintenance to inspect router and ISP status.",
        "Send a guest-facing update within 15 minutes.",
    ]
    assert opinion.departments == ["maintenance", "guest"]


def test_parse_opinion_blank_response_uses_explicit_blank_fallback() -> None:
    persona = build_persona()

    opinion = _parse_opinion(persona, "wifi complaint", "", "fake-model", 0.8)

    assert opinion.signal == ConciergeSignal.NEUTRAL
    assert opinion.conviction == pytest.approx(0.5)
    assert opinion.reasoning == "Seat returned a blank response."
    assert opinion.risk_factors == ["Seat response was empty — manual review suggested"]


@pytest.mark.asyncio
async def test_analyze_with_concierge_persona_retries_blank_response_with_empty_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persona = build_persona()
    calls: list[tuple[str, str, str]] = []

    async def fake_call_llm(
        system_prompt: str,
        user_prompt: str,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        calls.append((system_prompt, user_prompt, model))
        if len(calls) == 1:
            return ("", "fake-model")
        return (
            """
Signal: RESOLVE
Conviction: 0.74
Reasoning: The guest needs a concrete service recovery timeline before checkout.
Recommended Actions:
- Dispatch maintenance to inspect the network stack.
Departments: maintenance, guest
            """.strip(),
            "fake-model",
        )

    monkeypatch.setattr("backend.services.crog_concierge_engine._call_llm", fake_call_llm)
    monkeypatch.setattr("backend.services.crog_concierge_engine.ALLOW_CLOUD_LLM", True)
    monkeypatch.setattr("backend.services.crog_concierge_engine.FRONTIER_GATEWAY_API_KEY", "test-key")

    opinion = await analyze_with_concierge_persona(
        persona,
        case_brief="Guest reports unstable Wi-Fi before checkout.",
        context="Property above the timberline.",
    )

    assert len(calls) == 2
    assert "EMPTY_RESPONSE_HINT:" in calls[1][1]
    assert "EMPTY_RESPONSE:" in calls[1][1]
    assert calls[0][2] == "claude-sonnet-4-5-20250929"
    assert calls[1][2] == "gemini-2.5-pro"
    assert opinion.signal == ConciergeSignal.RESOLVE
    assert opinion.conviction == pytest.approx(0.74)
