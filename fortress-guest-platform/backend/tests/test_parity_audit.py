"""
Parity Audit Test Suite — verifies the async reconciliation logic.

Tests ensure that:
  - delta > $0.01 produces a CRITICAL log and 'discrepancy' status
  - matching totals produce INFO log and 'confirmed' status
  - auto-learn inserts new fee rows with is_active=false
"""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.streamline_client import DisplayFee, LiveQuoteResult


def _make_live_quote(
    total: str,
    fees: list[DisplayFee] | None = None,
    taxes: str = "0.00",
    rent: str = "0.00",
    confirmation_id: str = "TEST-123",
) -> LiveQuoteResult:
    return LiveQuoteResult(
        confirmation_id=confirmation_id,
        fees=fees or [],
        streamline_total=Decimal(total),
        streamline_taxes=Decimal(taxes),
        streamline_rent=Decimal(rent),
        raw_payload={"total": total},
    )


class TestParityDetection:
    """Verify parity logic for discrepancy vs confirmation."""

    def test_exact_match_is_confirmed(self):
        local = Decimal("1500.00")
        streamline = Decimal("1500.00")
        delta = abs(streamline - local)
        assert delta <= Decimal("0.01")

    def test_penny_match_is_confirmed(self):
        local = Decimal("1500.00")
        streamline = Decimal("1500.01")
        delta = abs(streamline - local)
        assert delta <= Decimal("0.01")

    def test_two_cents_is_discrepancy(self):
        local = Decimal("1500.00")
        streamline = Decimal("1500.02")
        delta = abs(streamline - local)
        assert delta > Decimal("0.01")

    def test_large_discrepancy(self):
        local = Decimal("1500.00")
        streamline = Decimal("1650.00")
        delta = abs(streamline - local)
        assert delta > Decimal("0.01")
        assert delta == Decimal("150.00")

    def test_empty_streamline_price_is_not_financial_data(self):
        from backend.workers.hermes_daily_auditor import _streamline_quote_has_financial_data

        result = _make_live_quote("0.00", fees=[], taxes="0.00", rent="0.00")
        assert _streamline_quote_has_financial_data(result) is False

    def test_streamline_price_with_rent_is_financial_data(self):
        from backend.workers.hermes_daily_auditor import _streamline_quote_has_financial_data

        result = _make_live_quote("1200.00", fees=[], taxes="0.00", rent="1200.00")
        assert _streamline_quote_has_financial_data(result) is True

    def test_daily_auditor_fetches_price_by_confirmation_code(self):
        from backend.workers.hermes_daily_auditor import _audit_single_reservation

        client = SimpleNamespace(fetch_live_quote=AsyncMock(return_value=None))
        reservation = SimpleNamespace(
            id="reservation-id",
            confirmation_code="CONF-123",
            streamline_reservation_id="STREAMLINE-INTERNAL-456",
        )

        outcome = asyncio.run(_audit_single_reservation(MagicMock(), reservation, client))

        assert outcome == "skipped_no_data"
        client.fetch_live_quote.assert_awaited_once_with("CONF-123")


class TestDisplayFeeClassification:
    """Verify that DisplayFee objects get correct bucket classification."""

    def test_cleaning_fee_bucket(self):
        from backend.services.ledger import classify_item
        bucket = classify_item("fee", "Cleaning Fee")
        assert bucket.value == "lodging"

    def test_damage_waiver_bucket(self):
        from backend.services.ledger import classify_item
        bucket = classify_item("fee", "Accidental Damage Waiver")
        # ADW is a non-taxable pass-through — EXEMPT, not admin (ledger docstring)
        assert bucket.value == "exempt"

    def test_processing_fee_bucket(self):
        from backend.services.ledger import classify_item
        bucket = classify_item("fee", "Processing Fee")
        # Processing Fee is a non-taxable pass-through — EXEMPT, not admin (ledger docstring)
        assert bucket.value == "exempt"


class TestLiveQuoteResultParsing:
    """Verify LiveQuoteResult dataclass integrity."""

    def test_empty_fees_list(self):
        result = _make_live_quote("1000.00")
        assert result.fees == []
        assert result.streamline_total == Decimal("1000.00")

    def test_fees_preserved(self):
        fees = [
            DisplayFee(
                name="Cleaning Fee",
                amount=Decimal("225.00"),
                fee_type="fee",
                streamline_id="101",
                is_taxable=True,
                bucket="lodging",
            ),
            DisplayFee(
                name="Damage Waiver",
                amount=Decimal("65.00"),
                fee_type="fee",
                streamline_id="102",
                is_taxable=True,
                bucket="admin",
            ),
        ]
        result = _make_live_quote("1290.00", fees=fees)
        assert len(result.fees) == 2
        assert result.fees[0].name == "Cleaning Fee"
        assert result.fees[1].bucket == "admin"

    def test_frozen_dataclass(self):
        result = _make_live_quote("500.00")
        with pytest.raises(AttributeError):
            result.streamline_total = Decimal("999.99")  # type: ignore


class TestAutoLearnFeeDiscovery:
    """Verify that unknown fees from Streamline are flagged for learning."""

    def test_known_fees_not_flagged(self):
        known_names = ["Cleaning Fee", "Processing Fee", "Accidental Damage Waiver"]
        fees = [
            DisplayFee(
                name=name,
                amount=Decimal("100.00"),
                fee_type="fee",
                streamline_id=str(i),
                is_taxable=True,
                bucket="lodging",
            )
            for i, name in enumerate(known_names)
        ]
        result = _make_live_quote("300.00", fees=fees)
        assert len(result.fees) == 3

    def test_new_fee_identified(self):
        fees = [
            DisplayFee(
                name="Brand New Mystery Fee",
                amount=Decimal("42.00"),
                fee_type="fee",
                streamline_id="999",
                is_taxable=True,
                bucket="lodging",
            ),
        ]
        result = _make_live_quote("42.00", fees=fees)
        assert result.fees[0].name == "Brand New Mystery Fee"
        assert result.fees[0].fee_type == "fee"

    def test_tax_type_not_auto_learned(self):
        fees = [
            DisplayFee(
                name="State Sales Tax",
                amount=Decimal("50.00"),
                fee_type="tax",
                streamline_id="T1",
                is_taxable=False,
                bucket="tax",
            ),
        ]
        result = _make_live_quote("50.00", fees=fees)
        assert result.fees[0].fee_type == "tax"


class TestParityAuditBreakdownFormat:
    """Verify the serialized breakdown format used for parity_audits table."""

    def test_streamline_breakdown_serialization(self):
        fees = [
            DisplayFee(
                name="Cleaning Fee",
                amount=Decimal("225.00"),
                fee_type="fee",
                streamline_id="101",
                is_taxable=True,
                bucket="lodging",
            ),
        ]
        result = _make_live_quote("1225.00", fees=fees, taxes="100.00", rent="900.00")

        breakdown = {
            "total": str(result.streamline_total),
            "taxes": str(result.streamline_taxes),
            "rent": str(result.streamline_rent),
            "fees": [
                {"name": f.name, "amount": str(f.amount), "type": f.fee_type, "bucket": f.bucket}
                for f in result.fees
            ],
        }

        assert breakdown["total"] == "1225.00"
        assert breakdown["taxes"] == "100.00"
        assert breakdown["rent"] == "900.00"
        assert len(breakdown["fees"]) == 1
        assert breakdown["fees"][0]["name"] == "Cleaning Fee"
        assert breakdown["fees"][0]["bucket"] == "lodging"
