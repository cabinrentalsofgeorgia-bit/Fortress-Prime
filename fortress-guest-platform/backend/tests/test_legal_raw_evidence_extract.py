"""Tests for raw-evidence graph/claim extraction (legal_case_graph)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import run  # noqa: F401  # Runtime import fallback used by production launch.

from backend.services.legal_case_graph import RawEvidenceExtraction, extract_raw_evidence_from_text


@pytest.mark.asyncio
async def test_extract_raw_evidence_falls_back_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.text = "not json at all {{{"
    monkeypatch.setattr(
        "backend.services.legal_case_graph.execute_resilient_inference",
        AsyncMock(return_value=mock_result),
    )
    db = AsyncMock()
    out = await extract_raw_evidence_from_text(
        db,
        "Some long text about the case and the opposing party.",
        source_document="memo.txt",
    )
    assert isinstance(out, RawEvidenceExtraction)
    assert len(out.nodes) >= 1
    assert len(out.claims) >= 1


@pytest.mark.asyncio
async def test_extract_raw_evidence_parses_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.text = (
        '{"nodes":[{"entity_type":"person","label":"Jane","source_document":"",'
        '"metadata":{}}],"edges":[],"claims":['
        '{"category":"CLAIM","content":"She signed.","rationale":"text"}]}'
    )
    monkeypatch.setattr(
        "backend.services.legal_case_graph.execute_resilient_inference",
        AsyncMock(return_value=mock_result),
    )
    db = AsyncMock()
    out = await extract_raw_evidence_from_text(db, "Jane signed the agreement.")
    assert any(n.label == "Jane" for n in out.nodes)
    assert len(out.claims) == 1
    assert out.claims[0].content == "She signed."
