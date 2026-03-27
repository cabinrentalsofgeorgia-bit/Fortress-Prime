from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.revenue_chain_of_custody import (
    build_signed_quote_record,
    calculate_fannin_county_tax,
)


def test_fannin_county_tax_is_deterministic() -> None:
    result = calculate_fannin_county_tax(raw_total="100.00", nights=2)

    assert result.raw_total == "100.00"
    assert result.percentage_tax == "6.00"
    assert result.nightly_fee_total == "10.00"
    assert result.tax_total == "16.00"
    assert result.quoted_total == "116.00"
    assert result.tax_rule == "fannin_county_v1"


def test_signed_quote_record_uses_canonical_payload_shape() -> None:
    record = build_signed_quote_record(
        quote_id="quote-123",
        raw_total="250.00",
        tax_total="30.00",
        timestamp="2026-03-19T12:00:00Z",
        secret="spark-secret",
    )

    expected_payload = {
        "quote_id": "quote-123",
        "raw_total": "250.00",
        "tax_total": "30.00",
        "timestamp": "2026-03-19T12:00:00Z",
    }
    expected_sig = hmac.new(
        b"spark-secret",
        json.dumps(expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert record == {**expected_payload, "hmac_sig": expected_sig}
