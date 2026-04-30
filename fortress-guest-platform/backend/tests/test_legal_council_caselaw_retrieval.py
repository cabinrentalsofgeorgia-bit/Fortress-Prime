"""
Tests for Legal Council precedent retrieval — ensures the council now pulls
controlling-authority chunks from the legal_caselaw_v2 Qdrant collection in
addition to the existing legal_ediscovery evidence retrieval, keeps the
merged context within the configured token budget, stamps seat prompts with
citation discipline, and threads caselaw opinion ids into the vault payload.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.services import legal_council as lc


# ── Qdrant mock scaffolding ────────────────────────────────────────────

def _caselaw_point(opinion_id: int, chunk_index: int, text: str, case_name: str = "Smith v. Jones") -> Dict[str, Any]:
    return {
        "id": f"{opinion_id}-{chunk_index}",
        "score": 0.9,
        "payload": {
            "opinion_id": opinion_id,
            "cluster_id": opinion_id + 1000,
            "case_name": case_name,
            "court": "Court of Appeals of Georgia",
            "date_filed": "2022-05-10",
            "citation": ["123 Ga. App. 456"],
            "chunk_index": chunk_index,
            "text_chunk": text,
        },
    }


def _evidence_point(point_id: str, text: str, case_slug: str = "matter-001") -> Dict[str, Any]:
    return {
        "id": point_id,
        "score": 0.8,
        "payload": {
            "case_slug": case_slug,
            "document_id": "doc-abc",
            "file_name": "Exhibit-A.pdf",
            "chunk_index": 0,
            "text": text,
        },
    }


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """
    Minimal drop-in for httpx.AsyncClient.
    Routes POSTs to /collections/<name>/points/search to the matching stub in
    a collection -> result-list registry so callers can script responses per
    Qdrant collection.
    """

    def __init__(self, registry: Dict[str, List[Dict[str, Any]]], *_, **__):
        self._registry = registry

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url: str, json: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> _FakeResponse:
        for name, results in self._registry.items():
            if f"/collections/{name}/points/search" in url:
                return _FakeResponse({"result": results})
        return _FakeResponse({"result": []})


@pytest.fixture
def mock_qdrant(monkeypatch: pytest.MonkeyPatch):
    """Install a per-test Qdrant stub. Returns a registry the test can populate."""
    registry: Dict[str, List[Dict[str, Any]]] = {}

    def _factory(*args, **kwargs):
        return _FakeAsyncClient(registry, *args, **kwargs)

    monkeypatch.setattr(lc.httpx, "AsyncClient", _factory)
    return registry


@pytest.fixture
def mock_embed(monkeypatch: pytest.MonkeyPatch):
    """Return a non-None deterministic embedding so freeze paths don't early-exit.

    Phase A PR #2: caselaw + library queries route through `_embed_legal_query`
    (2048-dim sovereign legal-embed); ediscovery + privileged still ride
    `_embed_text` (768-dim nomic). Mock both so either path is intercepted.
    """
    from backend.core.vector_db import LEGAL_EMBED_DIM

    async def fake_embed_nomic(text: str):
        return [0.1] * lc._cfg.embed_dim

    async def fake_embed_legal(text: str):
        return [0.1] * LEGAL_EMBED_DIM

    monkeypatch.setattr(lc, "_embed_text", fake_embed_nomic)
    monkeypatch.setattr(lc, "_embed_legal_query", fake_embed_legal)


# ═══════════════════════════════════════════════════════════════════════
# 1. Caselaw block appears in assembled context
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_council_context_includes_caselaw_block(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    mock_embed,
) -> None:
    mock_qdrant["legal_caselaw_v2"] = [
        _caselaw_point(
            111, 0,
            "The insurer owes a duty of good faith in settlement negotiations.",
            case_name="Acme Ins. v. Doe",
        ),
    ]
    mock_qdrant["legal_ediscovery"] = [
        _evidence_point("ev-1", "Defendant filed answer on the due date."),
    ]

    refs, chunks = await lc.freeze_caselaw_context("What duty does the insurer owe?", top_k=5)
    assert refs == ["caselaw:111:0"]
    assert chunks, "expected at least one caselaw chunk"

    evidence_ids, evidence_chunks = await lc.freeze_context("case", top_k=5)
    combined_caselaw, combined_evidence = lc._enforce_context_budget(chunks, evidence_chunks)
    context = lc.assemble_frozen_context(combined_caselaw, combined_evidence)

    assert lc.CASELAW_CONTEXT_HEADER in context
    assert lc.EVIDENCE_CONTEXT_HEADER in context
    assert "[CASE LAW: Acme Ins. v. Doe, Court of Appeals of Georgia (2022-05-10) — 123 Ga. App. 456]" in context
    assert context.index(lc.CASELAW_CONTEXT_HEADER) < context.index(lc.EVIDENCE_CONTEXT_HEADER), \
        "caselaw (authority) must precede evidence in the merged context"


# ═══════════════════════════════════════════════════════════════════════
# 2. Caselaw retrieval respects top_k
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_council_caselaw_retrieval_respects_top_k(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    mock_embed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_qdrant["legal_caselaw_v2"] = [
        _caselaw_point(i, 0, f"Authority chunk {i}.") for i in range(20)
    ]

    captured_limits: List[int] = []
    original_post = _FakeAsyncClient.post

    async def capture_post(self, url, json=None, headers=None):  # type: ignore[no-untyped-def]
        if "legal_caselaw_v2" in url and json:
            captured_limits.append(int(json.get("limit", -1)))
        # Respect the limit so the returned payload size matches the request.
        if "legal_caselaw_v2" in url and json:
            limit = int(json.get("limit", 0))
            payload = {"result": mock_qdrant["legal_caselaw_v2"][:limit]}
            return _FakeResponse(payload)
        return await original_post(self, url, json=json, headers=headers)

    monkeypatch.setattr(_FakeAsyncClient, "post", capture_post)

    refs, chunks = await lc.freeze_caselaw_context("query", top_k=7)
    assert captured_limits == [7]
    assert len(refs) == 7
    assert len(chunks) == 7


# ═══════════════════════════════════════════════════════════════════════
# 3. Context budget is enforced — evidence gets trimmed first
# ═══════════════════════════════════════════════════════════════════════

def test_council_context_budget_enforced() -> None:
    big = "x" * 4000  # ~1000 tokens per chunk at 4 chars/token
    caselaw = [f"[CASE LAW: A v. B, … — …]\n{big}" for _ in range(3)]
    evidence = [f"[ev-{i}] {big}" for i in range(10)]

    # Budget = 3000 tokens = 12_000 chars. Caselaw alone (3 * ~4025 = 12_075)
    # already exceeds budget; evidence must be dropped entirely and caselaw
    # retains at least the top-ranked chunk.
    kept_caselaw, kept_evidence = lc._enforce_context_budget(caselaw, evidence, budget_tokens=3000)
    assert kept_evidence == []
    assert len(kept_caselaw) >= 1

    # Budget = 10_000 tokens = 40_000 chars: all 3 caselaw fit (12k chars),
    # then evidence fills until we get close to 40k chars.
    kept_caselaw2, kept_evidence2 = lc._enforce_context_budget(caselaw, evidence, budget_tokens=10_000)
    assert len(kept_caselaw2) == 3
    assert 0 < len(kept_evidence2) < 10
    total = sum(len(c) for c in kept_caselaw2) + sum(len(c) for c in kept_evidence2)
    assert total <= 10_000 * 4

    # Roomy budget: everything fits.
    kept_all_caselaw, kept_all_evidence = lc._enforce_context_budget(caselaw, evidence, budget_tokens=100_000)
    assert kept_all_caselaw == caselaw
    assert kept_all_evidence == evidence


# ═══════════════════════════════════════════════════════════════════════
# 4. Seat system prompt carries the citation-discipline instruction
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_council_seat_prompt_contains_citation_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persona = lc.LegalPersona(
        name="The Test Seat",
        slug="test-seat",
        seat=1,
        archetype="test",
        domain="legal",
        god_head_domain="legal",
        worldview="Prefer defensible, grounded analysis.",
        bias=["Ground claims in authority."],
        focus_areas=["Citations"],
        trigger_events=["test event"],
        godhead_prompt="You are The Test Seat.",
        vector_collection="legal_library_v2",
    )

    captured: Dict[str, str] = {}

    async def fake_call_llm(
        system_prompt: str,
        user_prompt: str,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return (
            '{"signal":"NEUTRAL","conviction":0.5,"reasoning":"ok",'
            '"defense_arguments":[],"risk_factors":[],"recommended_actions":[]}',
            "fake-model",
        )

    monkeypatch.setattr(lc, "_call_llm", fake_call_llm)

    await lc.analyze_with_persona(persona, case_brief="Brief", context="op-ctx")
    assert "CITATION DISCIPLINE" in captured["system"]
    assert "cite only from the [CASE LAW: ...] blocks" in captured["system"]
    assert "Do not invent citations" in captured["system"]


# ═══════════════════════════════════════════════════════════════════════
# 5. Vaulted deliberation records caselaw opinion ids
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_vaulted_deliberation_records_caselaw_opinion_ids(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    mock_embed,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    mock_qdrant["legal_caselaw_v2"] = [
        _caselaw_point(42, 0, "Authority chunk 42."),
        _caselaw_point(77, 1, "Authority chunk 77."),
    ]
    mock_qdrant["legal_ediscovery"] = [
        _evidence_point("ev-1", "Evidence chunk 1."),
    ]

    captured_vault_args: Dict[str, Any] = {}

    def fake_vault_deliberation(
        case_slug: str,
        case_number,
        trigger_type: str,
        vector_ids: list,
        context_chunks: list,
        user_prompt: str,
        roster_snapshot: dict,
        seat_opinions: list,
        counsel_results: dict,
        execution_time_ms: int,
    ):
        captured_vault_args["case_slug"] = case_slug
        captured_vault_args["vector_ids"] = list(vector_ids)
        captured_vault_args["context_chunks"] = list(context_chunks)
        return ("event-xyz", "a" * 64)

    monkeypatch.setattr(lc, "vault_deliberation", fake_vault_deliberation)

    monkeypatch.setattr(lc, "_build_roster_snapshot", lambda: {"roster_version": "test", "seats": []})

    # Single-persona roster — keeps the fan-out deterministic.
    persona = lc.LegalPersona(
        name="Seat 1",
        slug="seat-1",
        seat=1,
        archetype="test",
        domain="legal",
        god_head_domain="legal",
        worldview="test",
        bias=["b"],
        focus_areas=["f"],
        trigger_events=["e"],
        godhead_prompt="prompt",
        vector_collection="legal_library_v2",
    )
    monkeypatch.setattr(lc.LegalPersona, "load_all", staticmethod(lambda: [persona]))

    async def fake_analyze(_persona, _brief, _context):
        return lc.LegalOpinion(
            persona_name="Seat 1",
            seat=1,
            slug="seat-1",
            event="test event",
            signal=lc.LegalSignal.NEUTRAL,
            conviction=0.5,
            reasoning="ok",
            defense_arguments=[],
            risk_factors=[],
            recommended_actions=[],
            timestamp="now",
            model_used="fake",
            elapsed_seconds=0.1,
        )

    monkeypatch.setattr(lc, "analyze_with_persona", fake_analyze)

    await lc.run_council_deliberation(
        session_id="sess-1",
        case_brief="brief",
        context="",
        progress_callback=None,
        case_slug="matter-001",
        case_number="CASE-1",
        trigger_type="TEST",
    )

    refs = captured_vault_args["vector_ids"]
    assert any(r.startswith("caselaw:42:") for r in refs)
    assert any(r.startswith("caselaw:77:") for r in refs)
    # Evidence UUIDs stay bare (no "caselaw:" prefix).
    assert any(r == "ev-1" for r in refs)


# ═══════════════════════════════════════════════════════════════════════
# 6. Regression: legal_ediscovery retrieval behavior unchanged
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ediscovery_retrieval_unchanged(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    mock_embed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    freeze_context must still:
      - return (vector_ids, chunks) from legal_ediscovery only
      - apply case_slug filter when the collection is legal_ediscovery
      - format chunks as "[{source}] {text}"
    """
    mock_qdrant["legal_ediscovery"] = [
        _evidence_point("ev-A", "Alpha chunk", case_slug="matter-001"),
        _evidence_point("ev-B", "Beta chunk", case_slug="matter-001"),
    ]
    mock_qdrant["legal_caselaw_v2"] = [_caselaw_point(9, 0, "should not appear in this result")]

    captured_bodies: List[Dict[str, Any]] = []
    original_post = _FakeAsyncClient.post

    async def capture_post(self, url, json=None, headers=None):  # type: ignore[no-untyped-def]
        captured_bodies.append({"url": url, "json": json})
        return await original_post(self, url, json=json, headers=headers)

    monkeypatch.setattr(_FakeAsyncClient, "post", capture_post)

    vector_ids, chunks = await lc.freeze_context(
        "brief", top_k=20, case_slug="matter-001",
    )

    # Only ediscovery was queried by freeze_context.
    hit_urls = [b["url"] for b in captured_bodies]
    assert any("legal_ediscovery" in u for u in hit_urls)
    assert not any("legal_caselaw_v2" in u for u in hit_urls)

    # case_slug filter applied.
    ediscovery_body = next(b for b in captured_bodies if "legal_ediscovery" in b["url"])
    filt = ediscovery_body["json"].get("filter", {})
    assert filt == {"must": [{"key": "case_slug", "match": {"value": "matter-001"}}]}

    # Shape is still (ids, "[file] text" strings).
    assert vector_ids == ["ev-A", "ev-B"]
    assert chunks == ["[Exhibit-A.pdf] Alpha chunk", "[Exhibit-A.pdf] Beta chunk"]


# ═══════════════════════════════════════════════════════════════════════
# Phase A PR #2 — encoder-routing assertion
# Caselaw retrieval must use `_embed_legal_query` (2048-dim legal-embed),
# ediscovery retrieval must use `_embed_text` (768-dim nomic).
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_freeze_caselaw_uses_legal_embed_router(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
):
    """Cutover guard: freeze_caselaw_context() must dispatch through
    _embed_legal_query (2048-dim legal-embed via gateway), not the legacy
    _embed_text path (768-dim nomic). Regressing this would silently
    re-route caselaw search to the wrong encoder + collection dim."""
    from backend.core.vector_db import LEGAL_EMBED_DIM

    legal_calls: List[str] = []
    nomic_calls: List[str] = []

    async def spy_legal(text: str):
        legal_calls.append(text[:32])
        return [0.1] * LEGAL_EMBED_DIM

    async def spy_nomic(text: str):
        nomic_calls.append(text[:32])
        return [0.1] * lc._cfg.embed_dim

    monkeypatch.setattr(lc, "_embed_legal_query", spy_legal)
    monkeypatch.setattr(lc, "_embed_text", spy_nomic)

    mock_qdrant["legal_caselaw_v2"] = [_caselaw_point(7, 0, "Sovereign caselaw chunk")]

    refs, chunks = await lc.freeze_caselaw_context("complaint alleges breach", top_k=5)

    assert legal_calls == ["complaint alleges breach"], legal_calls
    assert nomic_calls == [], nomic_calls
    assert refs and chunks
    assert refs[0].startswith("caselaw:")


@pytest.mark.asyncio
async def test_freeze_ediscovery_still_uses_legacy_nomic(
    mock_qdrant: Dict[str, List[Dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
):
    """Cutover guard: freeze_context() (ediscovery) MUST stay on the legacy
    _embed_text / 768-dim nomic encoder. Phase A PR #2 only cuts over
    caselaw + library; ediscovery deferred to PR #4."""
    legal_calls: List[str] = []
    nomic_calls: List[str] = []

    from backend.core.vector_db import LEGAL_EMBED_DIM

    async def spy_legal(text: str):
        legal_calls.append(text[:32])
        return [0.1] * LEGAL_EMBED_DIM

    async def spy_nomic(text: str):
        nomic_calls.append(text[:32])
        return [0.1] * lc._cfg.embed_dim

    monkeypatch.setattr(lc, "_embed_legal_query", spy_legal)
    monkeypatch.setattr(lc, "_embed_text", spy_nomic)

    mock_qdrant["legal_ediscovery"] = [
        _evidence_point("ev-1", "Email exhibit 1", case_slug="matter-007"),
    ]

    vector_ids, chunks = await lc.freeze_context(
        "discovery query", top_k=5, case_slug="matter-007",
    )

    assert nomic_calls == ["discovery query"], nomic_calls
    assert legal_calls == [], legal_calls
    assert vector_ids and chunks
