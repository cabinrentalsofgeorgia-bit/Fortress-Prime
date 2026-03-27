from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.api.openshell_audit import (
    summarize_historical_recovery,
    summarize_shadow_audits,
    summarize_shadow_seo_audits,
)
from backend.core.config import settings
from backend.services.shadow_mode_observer import run_shadow_audit


def _row(*, minutes_ago: int, drift_status: str, legacy_total: str, sovereign_total: str, tax_delta: str, base_rate_drift_pct: str):
    return SimpleNamespace(
        id=uuid4(),
        resource_id=str(uuid4()),
        outcome="success",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        metadata_json={
            "trace_id": str(uuid4()),
            "quote_id": str(uuid4()),
            "drift_status": drift_status,
            "legacy_total": legacy_total,
            "sovereign_total": sovereign_total,
            "tax_delta": tax_delta,
            "base_rate_drift_pct": base_rate_drift_pct,
            "hmac_signature": "abc123",
        },
    )


def _historical_row(*, hours_ago: int, outcome: str, slug: str, signature_valid: bool):
    return SimpleNamespace(
        id=uuid4(),
        resource_id=slug,
        outcome=outcome,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        metadata_json={
            "slug": slug,
            "signature_valid": signature_valid,
        },
    )


def _shadow_seo_row(
    *,
    minutes_ago: int,
    status: str,
    page_path: str,
    legacy_score: float,
    sovereign_score: float,
    uplift_pct_points: float,
):
    return SimpleNamespace(
        id=uuid4(),
        resource_id=str(uuid4()),
        outcome="success",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        metadata_json={
            "trace_id": str(uuid4()),
            "page_path": page_path,
            "property_slug": page_path.split("/")[-1],
            "status": status,
            "legacy_score": legacy_score,
            "sovereign_score": sovereign_score,
            "uplift_pct_points": uplift_pct_points,
            "legacy_rank": 7,
            "legacy_traffic": 123.4,
            "keyword": "blue ridge cabins",
            "observed_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
            "snapshot_path": "/tmp/semrush_shadow_snapshot.json",
        },
    )


def test_shadow_summary_reports_active_gate_metrics() -> None:
    rows = [
        _row(minutes_ago=1, drift_status="MATCH", legacy_total="100.00", sovereign_total="100.00", tax_delta="0.00", base_rate_drift_pct="0.0000"),
        _row(minutes_ago=2, drift_status="MINOR_DRIFT", legacy_total="100.00", sovereign_total="100.20", tax_delta="0.00", base_rate_drift_pct="0.2000"),
        _row(minutes_ago=3, drift_status="MATCH", legacy_total="150.00", sovereign_total="150.00", tax_delta="0.00", base_rate_drift_pct="0.0000"),
    ]

    summary = summarize_shadow_audits(rows)

    assert summary.status == "active"
    assert summary.gate_progress == "3/100"
    assert summary.spark_node_2_status == "online"
    assert summary.accuracy_rate == 0.6667
    assert summary.tax_accuracy_rate == 1.0
    assert summary.avg_base_drift_pct == 0.0667
    assert summary.kill_switch_armed is False
    assert len(summary.recent_traces) == 3


def test_shadow_summary_arms_kill_switch_on_critical_mismatch() -> None:
    rows = [
        _row(minutes_ago=20, drift_status="CRITICAL_MISMATCH", legacy_total="100.00", sovereign_total="110.50", tax_delta="5.00", base_rate_drift_pct="5.5000"),
    ]

    summary = summarize_shadow_audits(rows)

    assert summary.status == "alert"
    assert summary.critical_mismatch_count == 1
    assert summary.kill_switch_armed is True
    assert summary.spark_node_2_status == "idle"


def test_historical_recovery_summary_reports_resurrections_losses_and_signature_health() -> None:
    rows = [
        _historical_row(hours_ago=1, outcome="restored", slug="honeymoon-majestic-lake-cabin", signature_valid=True),
        _historical_row(hours_ago=2, outcome="cache_hit", slug="honeymoon-majestic-lake-cabin", signature_valid=True),
        _historical_row(hours_ago=3, outcome="restored", slug="wonderful-time", signature_valid=False),
        _historical_row(hours_ago=4, outcome="soft_landed", slug="missing-blueprint-slug", signature_valid=False),
        _historical_row(hours_ago=5, outcome="soft_landed", slug="missing-blueprint-slug", signature_valid=False),
        _historical_row(hours_ago=6, outcome="blueprint_unavailable", slug="skipped-event", signature_valid=False),
    ]

    summary = summarize_historical_recovery(rows, window_hours=24)

    assert summary.window_hours == 24
    assert summary.total_events == 5
    assert summary.total_resurrections == 3
    assert summary.soft_landed_losses == 2
    assert summary.valid_signature_count == 2
    assert summary.signature_health_pct == 40.0
    assert summary.top_recovered_slugs[0].slug == "honeymoon-majestic-lake-cabin"
    assert summary.top_recovered_slugs[0].count == 2
    assert summary.top_soft_landed_slugs[0].slug == "missing-blueprint-slug"
    assert summary.top_soft_landed_slugs[0].count == 2


def test_shadow_audit_returns_inactive_when_agentic_system_disabled() -> None:
    previous = settings.agentic_system_active
    settings.agentic_system_active = False
    try:
        result = asyncio.run(run_shadow_audit(payload={}))
    finally:
        settings.agentic_system_active = previous

    assert result["status"] == "inactive"
    assert "AGENTIC_SYSTEM_ACTIVE" in result["detail"]


def test_shadow_seo_summary_reports_uplift_and_trace_counts() -> None:
    rows = [
        _shadow_seo_row(
            minutes_ago=1,
            status="superior",
            page_path="/cabins/aska-escape-lodge",
            legacy_score=62.0,
            sovereign_score=98.0,
            uplift_pct_points=36.0,
        ),
        _shadow_seo_row(
            minutes_ago=2,
            status="parity",
            page_path="/cabins/wonderful-time",
            legacy_score=88.0,
            sovereign_score=90.0,
            uplift_pct_points=2.0,
        ),
        _shadow_seo_row(
            minutes_ago=3,
            status="trailing",
            page_path="/cabins/honeymoon-hideaway",
            legacy_score=94.0,
            sovereign_score=82.0,
            uplift_pct_points=-12.0,
        ),
    ]

    summary = summarize_shadow_seo_audits(rows)

    assert summary.status == "trailing"
    assert summary.observed_count == 3
    assert summary.superior_count == 1
    assert summary.parity_count == 1
    assert summary.trailing_count == 1
    assert summary.avg_legacy_score == 81.33
    assert summary.avg_sovereign_score == 90.0
    assert summary.avg_uplift_pct_points == 8.67
    assert summary.snapshot_path == "/tmp/semrush_shadow_snapshot.json"
    assert len(summary.recent_traces) == 3
