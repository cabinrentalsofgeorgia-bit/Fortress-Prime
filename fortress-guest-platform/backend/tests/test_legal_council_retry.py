"""Focused tests for Legal Council retry behavior."""

from __future__ import annotations

import run  # noqa: F401  # Install runtime import fallback used by production launch.

import pytest

from backend.services.legal_council import LegalPersona, LegalSignal, analyze_with_persona


def build_persona() -> LegalPersona:
    return LegalPersona(
        name="The Local Counsel",
        slug="local-counsel",
        seat=7,
        archetype="venue-savvy-practitioner",
        domain="legal",
        god_head_domain="legal",
        worldview="Think like practical county counsel.",
        bias=["Prefer filing-safe positions."],
        focus_areas=["Pleading tone", "Forum realism"],
        trigger_events=["pleading draft requested"],
        godhead_prompt="You are The Local Counsel.",
        vector_collection="legal_library_v2",
    )


def valid_json_response(
    signal: str = "STRONG_DEFENSE",
    conviction: float = 0.91,
    reasoning: str = "The defensive posture is strong.",
) -> str:
    return f"""
    {{
      "signal": "{signal}",
      "conviction": {conviction},
      "reasoning": "{reasoning}",
      "defense_arguments": ["Argument one"],
      "risk_factors": ["Risk one"],
      "recommended_actions": ["Action one"]
    }}
    """.strip()


@pytest.mark.asyncio
async def test_analyze_with_persona_accepts_valid_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    persona = build_persona()
    calls: list[tuple[str, str]] = []

    async def fake_call_llm(
        system_prompt: str,
        user_prompt: str,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        calls.append((system_prompt, user_prompt))
        return (valid_json_response(), "fake-model")

    monkeypatch.setattr("backend.services.legal_council._call_llm", fake_call_llm)

    opinion = await analyze_with_persona(
        persona,
        case_brief="CASE NUMBER: SUV2026000013\nDefendant has a viable defense posture.",
        context="Additional operator context.",
    )

    assert len(calls) == 1
    assert "REPAIR_HINT:" not in calls[0][1]
    assert opinion.signal == LegalSignal.STRONG_DEFENSE
    assert opinion.conviction == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_analyze_with_persona_retries_after_malformed_output(monkeypatch: pytest.MonkeyPatch) -> None:
    persona = build_persona()
    calls: list[tuple[str, str]] = []

    async def fake_call_llm(
        system_prompt: str,
        user_prompt: str,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        calls.append((system_prompt, user_prompt))
        if len(calls) == 1:
            return ("Absolutely, counselor. Here is my plain-English answer with no brace at all.", "fake-model")
        return (valid_json_response(), "fake-model")

    monkeypatch.setattr("backend.services.legal_council._call_llm", fake_call_llm)

    opinion = await analyze_with_persona(
        persona,
        case_brief="CASE NUMBER: SUV2026000013\nDefendant has a viable defense posture.",
        context="Additional operator context.",
    )

    assert len(calls) == 2
    assert "REPAIR_HINT:" in calls[1][1]
    assert "INVALID_RESPONSE_EXCERPT:" in calls[1][1]
    assert "plain-English answer with no brace" in calls[1][1]
    assert opinion.persona_name == "The Local Counsel"
    assert opinion.signal == LegalSignal.STRONG_DEFENSE
    assert opinion.conviction == pytest.approx(0.91)
    assert opinion.defense_arguments == ["Argument one"]
    assert opinion.risk_factors == ["Risk one"]
    assert opinion.recommended_actions == ["Action one"]


@pytest.mark.asyncio
async def test_analyze_with_persona_falls_back_after_three_malformed_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persona = build_persona()
    calls: list[tuple[str, str]] = []

    async def fake_call_llm(
        system_prompt: str,
        user_prompt: str,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        calls.append((system_prompt, user_prompt))
        return ("No JSON here either, just prose.", "fake-model")

    monkeypatch.setattr("backend.services.legal_council._call_llm", fake_call_llm)

    opinion = await analyze_with_persona(
        persona,
        case_brief="CASE NUMBER: SUV2026000013\nDefendant has a viable defense posture.",
        context="Additional operator context.",
    )

    assert len(calls) == 3
    assert "REPAIR_HINT:" in calls[1][1]
    assert "REPAIR_HINT:" in calls[2][1]
    assert opinion.persona_name == "The Local Counsel"
    assert opinion.signal == LegalSignal.NEUTRAL
    assert opinion.conviction == pytest.approx(0.5)
    assert opinion.defense_arguments == []
    assert opinion.risk_factors == ["LLM response required manual extraction"]
    assert opinion.recommended_actions == ["Review raw analysis or retry deliberation"]
