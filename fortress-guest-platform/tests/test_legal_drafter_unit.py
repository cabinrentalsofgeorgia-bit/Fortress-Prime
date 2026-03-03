from types import SimpleNamespace

import pytest

from backend.services import legal_drafter


def _claim(
    claim_number="CLM-001",
    damage_description="Broken lamp and stained couch",
    policy_violations="Smoking inside cabin",
    damage_areas=None,
    estimated_cost=350.0,
    inspection_notes="Housekeeping observed smoke odor and ash.",
):
    return SimpleNamespace(
        claim_number=claim_number,
        damage_description=damage_description,
        policy_violations=policy_violations,
        damage_areas=damage_areas or ["Living Room"],
        estimated_cost=estimated_cost,
        inspection_notes=inspection_notes,
    )


def test_extract_relevant_clauses_finds_matches():
    agreement = """
    Security deposit deductions may be taken for damage beyond normal wear and tear.
    Smoking is strictly prohibited inside the property and incurs penalties.
    Guest is responsible for repair and cleaning fees resulting from violations.
    """
    clauses = legal_drafter._extract_relevant_clauses(
        agreement,
        damage_desc="Smoke and broken furniture",
        violations="smoking violation",
    )
    assert clauses
    assert any("smoking" in c.lower() or "security deposit" in c.lower() for c in clauses)


@pytest.mark.asyncio
async def test_call_llm_fallback_to_openai(monkeypatch):
    monkeypatch.setattr(legal_drafter.settings, "use_local_llm", True, raising=False)
    monkeypatch.setattr(legal_drafter.settings, "ollama_deep_model", "deep", raising=False)
    monkeypatch.setattr(legal_drafter.settings, "ollama_fast_model", "fast", raising=False)
    monkeypatch.setattr(legal_drafter.settings, "openai_api_key", "test-key", raising=False)
    monkeypatch.setattr(legal_drafter.settings, "openai_model", "gpt-4o", raising=False)

    async def _ollama_fail(model, system, user):
        raise RuntimeError("ollama unavailable")

    async def _openai_ok(system, user):
        return "openai response"

    monkeypatch.setattr(legal_drafter, "_ollama_chat", _ollama_fail)
    monkeypatch.setattr(legal_drafter, "_openai_chat", _openai_ok)

    text, model = await legal_drafter._call_llm("s", "u")
    assert text == "openai response"
    assert model == "gpt-4o"


@pytest.mark.asyncio
async def test_call_llm_total_failure(monkeypatch):
    monkeypatch.setattr(legal_drafter.settings, "use_local_llm", False, raising=False)
    monkeypatch.setattr(legal_drafter.settings, "openai_api_key", "", raising=False)

    text, model = await legal_drafter._call_llm("s", "u")
    assert "FAILED" in text
    assert model == "none"


@pytest.mark.asyncio
async def test_draft_legal_response_without_agreement(monkeypatch):
    async def _fake_call(system, user):
        return ("draft body", "test-model")

    monkeypatch.setattr(legal_drafter, "_call_llm", _fake_call)

    result = await legal_drafter.draft_legal_response(
        claim=_claim(),
        guest_name="John Doe",
        property_name="Cabin A",
        check_in="2026-02-01",
        check_out="2026-02-05",
        agreement_content=None,
        staff_notes=[{"processor_name": "Ops", "creation_date": "2026-02-05", "message": "Photo evidence attached"}],
    )
    assert result["draft"] == "draft body"
    assert result["model"] == "test-model"
    assert isinstance(result["clauses"], list)

