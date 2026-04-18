"""
Golden Fee Integrity Test — ensures the cleaning fee schedule in the
database matches the Commander-verified 2026 values exactly.

If this test fails, a sync script or migration has corrupted the fee
schedule. DO NOT update these values without explicit Commander approval
and a corresponding update to seed_property_fees.py.
"""

from decimal import Decimal

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

SHADOW_DSN = get_test_dsn()

GOLDEN_CLEANING_FEES: dict[str, Decimal] = {
    "above-the-timberline":                 Decimal("325.00"),
    "blue-ridge-lake-sanctuary":            Decimal("225.00"),
    "chase-mountain-dreams":                Decimal("200.00"),
    "cherokee-sunrise-on-noontootla-creek":  Decimal("150.00"),
    "cohutta-sunset":                       Decimal("150.00"),
    "creekside-green":                      Decimal("150.00"),
    "fallen-timber-lodge":                  Decimal("250.00"),
    "high-hopes":                           Decimal("200.00"),
    "restoration-luxury":                   Decimal("250.00"),
    "riverview-lodge":                      Decimal("250.00"),
    "serendipity-on-noontootla-creek":      Decimal("250.00"),
    "skyfall":                              Decimal("200.00"),
    "the-rivers-edge":                      Decimal("250.00"),
}


def _fetch_db_cleaning_fees() -> dict[str, Decimal]:
    conn = psycopg2.connect(SHADOW_DSN)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.slug, f.flat_amount
            FROM fees f
            JOIN property_fees pf ON pf.fee_id = f.id
            JOIN properties p ON p.id = pf.property_id
            WHERE p.is_active = true
              AND f.name ILIKE %s
              AND f.is_pet_fee = false
        """, ("%Cleaning Fee%",))
        results = {}
        for slug, amount in cur.fetchall():
            slug_clean = slug.strip()
            if slug_clean in results:
                results[slug_clean] = max(results[slug_clean], Decimal(str(amount)))
            else:
                results[slug_clean] = Decimal(str(amount))
        cur.close()
        return results
    finally:
        conn.close()


class TestGoldenCleaningFees:
    """Each cabin's cleaning fee must match the golden value exactly."""

    @pytest.fixture(scope="class")
    def db_fees(self) -> dict[str, Decimal]:
        return _fetch_db_cleaning_fees()

    @pytest.mark.parametrize("slug,expected", list(GOLDEN_CLEANING_FEES.items()))
    def test_cleaning_fee_matches_golden(
        self, db_fees: dict[str, Decimal], slug: str, expected: Decimal
    ) -> None:
        actual = db_fees.get(slug)
        assert actual is not None, (
            f"{slug}: NO cleaning fee found in DB — run seed_property_fees.py"
        )
        assert actual == expected, (
            f"{slug}: DB has ${actual} but golden value is ${expected}. "
            f"A sync script may have overwritten the verified fee."
        )

    def test_no_unknown_cabins_missing(self, db_fees: dict[str, Decimal]) -> None:
        missing = set(GOLDEN_CLEANING_FEES.keys()) - set(db_fees.keys())
        assert not missing, (
            f"Cabins missing from DB: {missing}. "
            f"Run seed_property_fees.py to restore."
        )


class TestProcessingFeeIntegrity:
    """Processing Fee two-rule logic (verified against Streamline vault data 2026):

      Non-VRBO: 6% of taxable base (rent + cleaning + party fees), no cap.
      VRBO/HA:  min(6%, $59.95 flat cap).

    Streamline fee description: "Processing Fee all but HA/VRBO" (percent_value=6).
    All 4 vault entries inspected match 6% exactly for Ring Central / direct bookings.
    """

    def test_processing_fee_is_percentage_type(self) -> None:
        conn = psycopg2.connect(SHADOW_DSN)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT fee_type, percentage_rate, flat_amount "
                "FROM fees WHERE name = 'Processing Fee' LIMIT 1"
            )
            row = cur.fetchone()
            assert row is not None, "Processing Fee row missing from fees table"
            fee_type, pct_rate, flat_amount = row
            assert fee_type == "percentage", (
                f"Processing Fee fee_type={fee_type}, must be 'percentage'"
            )
            assert Decimal(str(pct_rate)) == Decimal("6.000"), (
                f"Processing Fee rate={pct_rate}%, must be 6%"
            )
        finally:
            conn.close()

    # ── Non-VRBO: 6% of taxable base, no cap ──────────────────────────────────
    # Values verified against actual Streamline vault data (required_fees JSONB):
    #   53993: base=$1900 → fee=$114.00   (6% exact)
    #   54050: base=$2731 → fee=$163.86   (6% exact)
    #   53992: base=$1805 → fee=$108.30   (6% exact)
    #   53991: base=$1829 → fee=$109.74   (6% exact)
    @pytest.mark.parametrize("pct_base,expected_fee", [
        (Decimal("1900.00"), Decimal("114.00")),  # vault 53993 confirmed
        (Decimal("2731.00"), Decimal("163.86")),  # vault 54050 confirmed
        (Decimal("1805.00"), Decimal("108.30")),  # vault 53992 confirmed
        (Decimal("1829.00"), Decimal("109.74")),  # vault 53991 confirmed
        (Decimal("1630.00"), Decimal("97.80")),   # 6% × $1,630
        (Decimal("825.00"),  Decimal("49.50")),   # 6% × $825 (below VRBO cap, non-VRBO: no cap)
    ])
    def test_processing_fee_calculation_non_vrbo(
        self, pct_base: Decimal, expected_fee: Decimal
    ) -> None:
        from backend.services.pricing_service import calculate_processing_fee
        actual = calculate_processing_fee(pct_base, booking_source=None)
        assert actual == expected_fee, (
            f"Non-VRBO 6% of ${pct_base} = ${actual}, expected ${expected_fee}"
        )

    # ── VRBO/HA: capped at $59.95 ─────────────────────────────────────────────
    @pytest.mark.parametrize("pct_base,expected_fee", [
        # Low base: 6% < cap → full 6% applies
        (Decimal("500.00"),  Decimal("30.00")),   # 6% × $500 = $30.00 < $59.95
        (Decimal("800.00"),  Decimal("48.00")),   # 6% × $800 = $48.00 < $59.95
        (Decimal("998.33"),  Decimal("59.90")),   # 6% × $998.33 ≈ $59.90 < $59.95
        # High base: 6% > cap → capped at $59.95
        (Decimal("1000.00"), Decimal("59.95")),   # 6% × $1000 = $60.00 → capped at $59.95
        (Decimal("1500.00"), Decimal("59.95")),   # 6% × $1500 = $90.00 → capped at $59.95
        (Decimal("2000.00"), Decimal("59.95")),   # 6% × $2000 = $120.00 → capped at $59.95
    ])
    def test_processing_fee_calculation_vrbo_capped(
        self, pct_base: Decimal, expected_fee: Decimal
    ) -> None:
        from backend.services.pricing_service import calculate_processing_fee
        for source in ("ha-olb", "VRBO", "HomeAway", "HA"):
            actual = calculate_processing_fee(pct_base, booking_source=source)
            assert actual == expected_fee, (
                f"VRBO source={source!r} 6% of ${pct_base} capped at $59.95: "
                f"got ${actual}, expected ${expected_fee}"
            )

    def test_processing_fee_classified_as_exempt(self) -> None:
        from backend.services.ledger import classify_item, TaxBucket
        bucket = classify_item("fee", "Processing Fee")
        assert bucket == TaxBucket.EXEMPT

    def test_processing_fee_not_flat_81(self) -> None:
        """Guard: the old flat $81 must never reappear."""
        conn = psycopg2.connect(SHADOW_DSN)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT flat_amount FROM fees WHERE name = 'Processing Fee' LIMIT 1"
            )
            row = cur.fetchone()
            assert row is not None
            assert Decimal(str(row[0])) != Decimal("81.00"), (
                "Processing Fee has reverted to flat $81.00 — "
                "run seed_property_fees.py to restore 6% percentage model"
            )
        finally:
            conn.close()


class TestLedgerTaxBucketCoverage:
    """Verify that the cleaning fee is taxed correctly by the Ledger."""

    def test_cleaning_fee_classified_as_lodging(self) -> None:
        from backend.services.ledger import classify_item, TaxBucket
        bucket = classify_item("fee", "Cleaning Fee - blue-ridge-lake-sanctuary")
        assert bucket == TaxBucket.LODGING, (
            f"Cleaning fee classified as {bucket}, must be LODGING"
        )

    def test_cleaning_fee_in_all_three_tax_bases(self) -> None:
        from backend.services.ledger import (
            BucketedItem, TaxBucket, resolve_taxes,
        )
        items = [
            BucketedItem(name="Base Rent", amount=Decimal("598.00"),
                         item_type="rent", bucket=TaxBucket.LODGING),
            BucketedItem(name="Cleaning Fee", amount=Decimal("225.00"),
                         item_type="fee", bucket=TaxBucket.LODGING),
        ]
        result = resolve_taxes(items, "Fannin", nights=2)

        taxable_base = Decimal("823.00")  # 598 + 225

        assert result.state_sales_tax == Decimal("32.92"), (
            f"State sales tax: expected $32.92, got ${result.state_sales_tax}"
        )
        assert result.county_sales_tax == Decimal("24.69"), (
            f"County sales tax: expected $24.69, got ${result.county_sales_tax}"
        )
        assert result.lodging_tax == Decimal("49.38"), (
            f"Lodging tax: expected $49.38, got ${result.lodging_tax}"
        )

        for detail in result.details:
            if "State Sales" in detail.tax_name and "Goods" not in detail.tax_name:
                assert detail.taxable_base == taxable_base
            elif "County Sales" in detail.tax_name and "Goods" not in detail.tax_name:
                assert detail.taxable_base == taxable_base
            elif "Lodging Tax" in detail.tax_name:
                assert detail.taxable_base == taxable_base

    def test_dot_fee_is_flat_per_night_not_percentage(self) -> None:
        from backend.services.ledger import (
            BucketedItem, TaxBucket, resolve_taxes,
        )
        items = [
            BucketedItem(name="Base Rent", amount=Decimal("1000.00"),
                         item_type="rent", bucket=TaxBucket.LODGING),
        ]
        result_2n = resolve_taxes(items, "Fannin", nights=2)
        result_5n = resolve_taxes(items, "Fannin", nights=5)

        assert result_2n.dot_fee == Decimal("10.00"), (
            f"DOT for 2 nights: expected $10.00, got ${result_2n.dot_fee}"
        )
        assert result_5n.dot_fee == Decimal("25.00"), (
            f"DOT for 5 nights: expected $25.00, got ${result_5n.dot_fee}"
        )
        assert result_2n.state_sales_tax == result_5n.state_sales_tax, (
            "DOT should not affect sales tax — it's a flat per-night addition"
        )
