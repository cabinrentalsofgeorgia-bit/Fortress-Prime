"""Funnel edge math (Strike 10) — pure aggregation."""

from backend.services.funnel_analytics_service import compute_funnel_edges


def test_compute_funnel_edges_retention_and_leakage() -> None:
    sessions = {
        "a": {"page_view", "property_view", "quote_open", "checkout_step", "funnel_hold_started"},
        "b": {"page_view", "property_view", "quote_open"},
        "c": {"page_view", "property_view"},
        "d": {"page_view"},
    }
    edges = compute_funnel_edges(sessions)
    assert len(edges) == 4

    pv_prop = next(e for e in edges if e.from_stage == "page_view")
    assert pv_prop.from_count == 4
    assert pv_prop.to_count == 3
    assert pv_prop.retention_pct == 75.0
    assert pv_prop.leakage_pct == 25.0

    q_co = next(e for e in edges if e.from_stage == "quote_open")
    assert q_co.from_count == 2
    assert q_co.to_count == 1
    assert q_co.retention_pct == 50.0
    assert q_co.leakage_pct == 50.0


def test_compute_funnel_edges_empty() -> None:
    assert compute_funnel_edges({})[0].from_count == 0
