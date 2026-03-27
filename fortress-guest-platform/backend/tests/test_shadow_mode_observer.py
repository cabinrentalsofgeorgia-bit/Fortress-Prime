from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.shadow_mode_observer import (
    ComparisonResult,
    QuoteSnapshot,
    compare_snapshots,
    render_report,
    sign_audit_payload,
)


def _snapshot(*, taxes: str, total: str, base_rent: str = "250.00", fees: str = "40.00") -> QuoteSnapshot:
    return QuoteSnapshot(
        property_id="property-1",
        property_name="Bear Creek Lodge",
        requested_property_id="14",
        pricing_source="streamline_rate_card",
        check_in="2026-05-23",
        check_out="2026-05-26",
        nights=3,
        base_rent=Decimal(base_rent),
        fees=Decimal(fees),
        taxes=Decimal(taxes),
        total_amount=Decimal(total),
        raw_total=Decimal(base_rent) + Decimal(fees),
        metadata={},
    )


def test_compare_snapshots_returns_match_for_identical_quote() -> None:
    legacy = _snapshot(taxes="32.00", total="322.00")
    sovereign = _snapshot(taxes="32.00", total="322.00")

    comparison = compare_snapshots(legacy, sovereign, tolerance=Decimal("0.01"))

    assert comparison.drift_status == "MATCH"
    assert comparison.tax_delta == Decimal("0.00")
    assert comparison.base_rate_drift_pct == Decimal("0.0000")


def test_compare_snapshots_returns_critical_mismatch_for_tax_drift() -> None:
    legacy = _snapshot(taxes="32.00", total="322.00")
    sovereign = _snapshot(taxes="49.00", total="339.00")

    comparison = compare_snapshots(legacy, sovereign, tolerance=Decimal("0.01"))

    assert comparison.drift_status == "CRITICAL_MISMATCH"
    assert comparison.tax_delta == Decimal("17.00")


def test_render_report_includes_trace_and_signature() -> None:
    legacy = _snapshot(taxes="32.00", total="322.00")
    sovereign = _snapshot(taxes="32.00", total="322.00")
    comparison = ComparisonResult(
        trace_id="trace-123",
        timestamp="2026-03-19T12:00:00Z",
        drift_status="MATCH",
        legacy_total=Decimal("322.00"),
        sovereign_total=Decimal("322.00"),
        total_delta=Decimal("0.00"),
        legacy_taxes=Decimal("32.00"),
        sovereign_taxes=Decimal("32.00"),
        tax_delta=Decimal("0.00"),
        legacy_base_rent=Decimal("250.00"),
        sovereign_base_rent=Decimal("250.00"),
        base_rate_delta=Decimal("0.00"),
        base_rate_drift_pct=Decimal("0.0000"),
        notes=[],
    )
    signature = sign_audit_payload({"trace_id": "trace-123", "drift_status": "MATCH"})

    report = render_report(
        request_payload={"property_id": "14"},
        legacy=legacy,
        sovereign=sovereign,
        comparison=comparison,
        hmac_signature=signature,
    )

    assert "Trace ID" in report
    assert "Legacy Total" in report
    assert "Sovereign Total" in report
    assert "Drift Status" in report
    assert "HMAC Signature" in report
