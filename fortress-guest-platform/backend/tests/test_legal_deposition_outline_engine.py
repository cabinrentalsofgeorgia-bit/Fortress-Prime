"""Unit tests for deposition outline fallback schema and provenance."""

from __future__ import annotations

import run  # noqa: F401  # Installs .pyc fallback finder used by production launch.

from backend.services.legal_deposition_outline_engine import (
    EMPTY_PROVENANCE,
    _build_outline_metadata,
    _fallback_outline_body,
    _normalize_pressure_points_list,
)


def test_fallback_outline_body_matches_production_pressure_schema() -> None:
    subgraph = {
        "nodes": [{"id": "n1", "label": "Alice"}],
        "edges": [{"id": "e1", "relationship_type": "CONTRADICTS", "source_node_id": "n1", "target_node_id": "n2"}],
    }
    alerts = [
        {
            "id": "alert-uuid-1",
            "alert_type": "RULE_11",
            "contradiction_summary": "Sworn statement conflicts with timeline.",
            "confidence_score": 90,
            "status": "ACTIVE",
            "created_at": None,
        }
    ]
    council = {
        "event_id": "evt-1",
        "timestamp": "2026-03-29T00:00:00+00:00",
        "consensus_signal": "VULNERABLE",
        "top_risk_factors": ["Signatory chain unclear"],
    }
    body = _fallback_outline_body(
        case_slug="case-x",
        deponent_entity="Alice",
        subgraph=subgraph,
        alerts=alerts,
        council=council,
        operator_focus="Yesterday's witness statements",
    )
    assert body["summary"].startswith("[Emergency Fallback]")
    assert isinstance(body["pressure_points"], list)
    assert body["pressure_points"]
    pp0 = body["pressure_points"][0]
    assert set(pp0.keys()) >= {"title", "rationale", "graph_hook", "alert_ref", "provenance"}
    prov = pp0["provenance"]
    for k in EMPTY_PROVENANCE:
        assert k in prov
    assert prov["source_system"] == "sanctions_alerts_v2"
    assert prov["sanctions_alert_id"] == "alert-uuid-1"
    assert prov["graph_edge_ids"] and "e1" in prov["graph_edge_ids"]
    assert isinstance(body["questioning_outline"], list)
    assert isinstance(body["exhibit_sequence"], list)
    assert isinstance(body["council_risk_factors"], list)
    assert isinstance(body["source_alert_summaries"], list)


def test_fallback_without_alerts_uses_council_pressure_points() -> None:
    body = _fallback_outline_body(
        case_slug="case-y",
        deponent_entity="Bob",
        subgraph={"nodes": [], "edges": []},
        alerts=[],
        council={
            "event_id": "evt-2",
            "top_risk_factors": ["Risk A", "Risk B"],
        },
        operator_focus=None,
    )
    assert body["pressure_points"]
    assert body["pressure_points"][0]["provenance"]["source_system"] == "council_deliberation"
    assert body["pressure_points"][0]["provenance"]["council_risk_factor_index"] == 0


def test_metadata_block_shape() -> None:
    meta = _build_outline_metadata(
        ingestion_timing={"ingestion_parallel_wall_ms": 12},
        graph_full={"nodes": [1, 2], "edges": [1]},
        subgraph={"nodes": [1], "edges": []},
        alerts=[{"id": "a"}],
        council_present=True,
        deliberation_ledger_seat_count=9,
        inference_primary_ms=100,
        inference_repair_ms=50,
        mode="llm",
        inference_source="ollama",
    )
    assert meta["mode"] == "llm"
    assert meta["inference_source"] == "ollama"
    assert meta["ingestion_row_counts"]["sanctions_alerts_returned"] == 1
    assert meta["ingestion_row_counts"]["deliberation_ledger_seat_opinions"] == 9
    assert meta["ingestion_row_counts"]["graph_nodes_full"] == 2
    assert meta["inference_latency_ms"]["total"] == 150


def test_normalize_pressure_points_backfills_provenance_from_alert_ref() -> None:
    alerts = [{"id": "aid-1", "contradiction_summary": "x"}]
    raw = [
        {
            "title": "T",
            "rationale": "R",
            "graph_hook": "G",
            "alert_ref": "aid-1",
        }
    ]
    out = _normalize_pressure_points_list(
        raw,
        alerts=alerts,
        council_event_id="ce-1",
        subgraph={"nodes": [], "edges": [{"id": "ex", "relationship_type": "CONTRADICTS"}]},
    )
    assert len(out) == 1
    assert out[0]["provenance"]["sanctions_alert_id"] == "aid-1"
    assert out[0]["provenance"]["council_event_id"] == "ce-1"
