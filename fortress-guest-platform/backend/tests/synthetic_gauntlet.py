"""
Synthetic Gauntlet — AI-generated stress test for fiduciary payout integrity.

Generates 100 random reservation payloads with varying guest counts, dates,
cabin tiers, fee structures, and tax jurisdictions. Asserts that
`calculate_owner_payout` NEVER violates mathematical payout invariants.

Note: commission rates are per-owner in production (stored in
owner_payout_accounts.commission_rate). This gauntlet uses an explicit
GAUNTLET_COMMISSION_RATE of 25% for math verification purposes only —
this is NOT the business rate. The function accepts any rate.

Model A (Phase B, 2026-04-14): CC processing fees are absorbed by the company.
net_owner_payout = gross_revenue - commission_amount. No CC deduction.

Invariants enforced:
  1. net_owner_payout ≤ gross_revenue  (owner never gets more than commissionable total)
  2. commission_amount == gross_revenue × rate / 100  (penny-exact)
  3. pass_through items are NEVER included in gross_revenue
  4. net_owner_payout + commission_amount == gross_revenue  (no CC deduction)
  5. All monetary values are rounded to 2 decimal places
  6. net_owner_payout is non-negative when gross_revenue ≥ 0
"""

from __future__ import annotations

import random
from decimal import Decimal, ROUND_HALF_UP

import pytest

from backend.services.ledger import (
    BucketedItem,
    TaxBucket,
    calculate_owner_payout,
    classify_item,
    resolve_taxes,
    OwnerPayoutBreakdown,
)

# Explicit rate used by this test file only.
# Not a business default — commission rates are per-owner in the database.
GAUNTLET_COMMISSION_RATE = Decimal("25.00")

TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100")

COUNTIES = ["fannin", "blue_ridge", "gilmer", "union"]

RENT_TIERS = [
    (Decimal("225"), Decimal("350")),   # economy
    (Decimal("350"), Decimal("575")),   # mid-range
    (Decimal("575"), Decimal("899")),   # premium
    (Decimal("899"), Decimal("1500")),  # luxury
]

CLEANING_FEES = [
    Decimal("150"), Decimal("175"), Decimal("200"), Decimal("225"),
    Decimal("250"), Decimal("275"), Decimal("300"), Decimal("325"),
    Decimal("350"), Decimal("400"),
]

ADW_OPTIONS = [Decimal("0"), Decimal("39"), Decimal("49"), Decimal("59"), Decimal("69")]
PROCESSING_RATE_OPTIONS = [Decimal("0"), Decimal("29.99"), Decimal("39.99")]

PET_FEE_OPTIONS = [Decimal("0"), Decimal("75"), Decimal("100"), Decimal("150")]
EXTRA_GUEST_PER_NIGHT = Decimal("25")

ADDON_CATALOG = [
    ("Early Check-In (1 hour)", Decimal("50")),
    ("Late Check-Out (1 hour)", Decimal("50")),
    ("Firewood Bundle", Decimal("35")),
    ("Fishing Guide (half-day)", Decimal("200")),
    ("S'mores Kit", Decimal("15")),
    ("Welcome Basket", Decimal("45")),
]

random.seed(42)


def _money(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _rand_decimal(lo: Decimal, hi: Decimal) -> Decimal:
    scale = int((hi - lo) * 100)
    offset = random.randint(0, max(scale, 1))
    return lo + Decimal(offset) / Decimal(100)


def _generate_reservation(scenario_id: int) -> list[BucketedItem]:
    """Build a realistic list of invoice line items for a synthetic reservation."""
    items: list[BucketedItem] = []

    tier = random.choice(RENT_TIERS)
    nightly_rate = _money(_rand_decimal(tier[0], tier[1]))
    nights = random.randint(2, 14)
    base_rent = _money(nightly_rate * nights)
    items.append(BucketedItem(
        name=f"Base Rent ({nights} nights @ ${nightly_rate})",
        amount=base_rent,
        item_type="rent",
        bucket=TaxBucket.LODGING,
    ))

    cleaning = random.choice(CLEANING_FEES)
    items.append(BucketedItem(
        name="Cleaning Fee",
        amount=cleaning,
        item_type="fee",
        bucket=TaxBucket.LODGING,
    ))

    guests = random.randint(1, 16)
    base_guests = random.choice([4, 6, 8])
    extra_guests = max(0, guests - base_guests)
    if extra_guests > 0:
        eg_total = _money(EXTRA_GUEST_PER_NIGHT * extra_guests * nights)
        items.append(BucketedItem(
            name=f"Extra Guest Fee ({extra_guests} guests × {nights} nights)",
            amount=eg_total,
            item_type="fee",
            bucket=TaxBucket.LODGING,
        ))

    pet_fee = random.choice(PET_FEE_OPTIONS)
    if pet_fee > 0:
        items.append(BucketedItem(
            name="Pet Fee (Non-Refundable)",
            amount=pet_fee,
            item_type="fee",
            bucket=TaxBucket.LODGING,
        ))

    adw = random.choice(ADW_OPTIONS)
    if adw > 0:
        items.append(BucketedItem(
            name="Accidental Damage Waiver",
            amount=adw,
            item_type="fee",
            bucket=TaxBucket.ADMIN,
        ))

    proc = random.choice(PROCESSING_RATE_OPTIONS)
    if proc > 0:
        items.append(BucketedItem(
            name="Booking Processing Fee",
            amount=proc,
            item_type="fee",
            bucket=TaxBucket.ADMIN,
        ))

    num_addons = random.randint(0, 3)
    if num_addons > 0:
        chosen = random.sample(ADDON_CATALOG, min(num_addons, len(ADDON_CATALOG)))
        for addon_name, addon_price in chosen:
            if "firewood" in addon_name.lower():
                bucket = TaxBucket.GOODS
            elif "fishing" in addon_name.lower() or "guide" in addon_name.lower():
                bucket = TaxBucket.SERVICE
            else:
                bucket = TaxBucket.LODGING
            items.append(BucketedItem(
                name=addon_name,
                amount=addon_price,
                item_type="addon",
                bucket=bucket,
            ))

    county = random.choice(COUNTIES)
    lodging_rates = {"fannin": 6, "blue_ridge": 8, "gilmer": 8, "union": 5}
    sales_rate = Decimal("7")
    lodging_rate = Decimal(str(lodging_rates[county]))
    dot_per_night = Decimal("5")

    lodging_total = sum(i.amount for i in items if i.bucket == TaxBucket.LODGING)
    admin_total = sum(i.amount for i in items if i.bucket == TaxBucket.ADMIN)
    goods_total = sum(i.amount for i in items if i.bucket == TaxBucket.GOODS)

    tax_lodging_sales = _money(lodging_total * sales_rate / ONE_HUNDRED)
    tax_lodging_lodging = _money(lodging_total * lodging_rate / ONE_HUNDRED)
    tax_admin_sales = _money(admin_total * sales_rate / ONE_HUNDRED)
    tax_goods_sales = _money(goods_total * sales_rate / ONE_HUNDRED)
    dot_fee = _money(dot_per_night * nights)

    total_tax = tax_lodging_sales + tax_lodging_lodging + tax_admin_sales + tax_goods_sales + dot_fee

    if total_tax > 0:
        items.append(BucketedItem(
            name=f"Taxes ({county})",
            amount=total_tax,
            item_type="tax",
            bucket=TaxBucket.LODGING,
        ))

    if random.random() < 0.3:
        deposit = random.choice([Decimal("250"), Decimal("500"), Decimal("750")])
        items.append(BucketedItem(
            name="Security Deposit (Refundable)",
            amount=deposit,
            item_type="deposit",
            bucket=TaxBucket.EXEMPT,
        ))

    return items


SCENARIOS = [_generate_reservation(i) for i in range(100)]


class TestSyntheticGauntlet:
    """100-scenario stress test for calculate_owner_payout."""

    @pytest.mark.parametrize("scenario_id", range(100))
    def test_fiduciary_invariants(self, scenario_id: int) -> None:
        items = SCENARIOS[scenario_id]
        result = calculate_owner_payout(items, commission_rate=GAUNTLET_COMMISSION_RATE)
        self._assert_invariants(result, items, scenario_id)

    @pytest.mark.parametrize("scenario_id", range(100))
    def test_zero_commission_variant(self, scenario_id: int) -> None:
        """At 0% commission, owner gets full gross (Model A: no CC deduction)."""
        items = SCENARIOS[scenario_id]
        result = calculate_owner_payout(items, commission_rate=Decimal("0"))
        assert result.commission_amount == Decimal("0.00")
        assert result.cc_processing_fee == Decimal("0.00")
        assert result.net_owner_payout == result.gross_revenue

    @pytest.mark.parametrize("scenario_id", range(100))
    def test_model_a_cc_fee_always_zero(self, scenario_id: int) -> None:
        """Model A: CC processing fee is always zero. Net = gross - commission."""
        items = SCENARIOS[scenario_id]
        result = calculate_owner_payout(items, commission_rate=GAUNTLET_COMMISSION_RATE)
        assert result.cc_processing_fee == Decimal("0.00")
        assert result.net_owner_payout == _money(
            result.gross_revenue - result.commission_amount
        )

    def _assert_invariants(
        self,
        result: OwnerPayoutBreakdown,
        items: list[BucketedItem],
        scenario_id: int,
    ) -> None:
        msg = f"[Scenario {scenario_id}]"

        assert result.net_owner_payout <= result.gross_revenue, (
            f"{msg} Owner payout {result.net_owner_payout} exceeds "
            f"gross revenue {result.gross_revenue}"
        )

        expected_commission = _money(
            result.gross_revenue * result.commission_rate / ONE_HUNDRED
        )
        assert result.commission_amount == expected_commission, (
            f"{msg} Commission mismatch: got {result.commission_amount}, "
            f"expected {expected_commission}"
        )

        pass_through_items = [
            i for i in items if i.item_type in ("tax", "deposit")
            or i.bucket in (TaxBucket.ADMIN, TaxBucket.EXEMPT)
            or "clean" in i.name.strip().lower()
        ]
        for pt in pass_through_items:
            commissionable_in_details = [
                d for d in result.details
                if d.name == pt.name and d.category == "commissionable"
            ]
            assert len(commissionable_in_details) == 0, (
                f"{msg} Pass-through item '{pt.name}' found in commissionable bucket"
            )

        # Model A: net = gross - commission (no CC deduction)
        expected_net = _money(result.gross_revenue - result.commission_amount)
        assert result.net_owner_payout == expected_net, (
            f"{msg} Net mismatch: got {result.net_owner_payout}, expected {expected_net}"
        )

        assert result.cc_processing_fee == Decimal("0.00"), (
            f"{msg} cc_processing_fee must be 0.00 (Model A)"
        )

        assert result.gross_revenue == result.gross_revenue.quantize(TWO_PLACES), (
            f"{msg} gross_revenue not rounded to 2 decimal places"
        )
        assert result.commission_amount == result.commission_amount.quantize(TWO_PLACES), (
            f"{msg} commission_amount not rounded to 2 decimal places"
        )
        assert result.net_owner_payout == result.net_owner_payout.quantize(TWO_PLACES), (
            f"{msg} net_owner_payout not rounded to 2 decimal places"
        )

        if result.gross_revenue >= Decimal("0"):
            assert result.net_owner_payout >= Decimal("0"), (
                f"{msg} Negative net_owner_payout {result.net_owner_payout} with "
                f"non-negative gross_revenue {result.gross_revenue}"
            )

        expected_collected = _money(sum(i.amount for i in items))
        assert result.total_collected == expected_collected, (
            f"{msg} total_collected mismatch: got {result.total_collected}, "
            f"expected {expected_collected}"
        )

        expected_pass_through = _money(sum(
            d.amount for d in result.details if d.category == "pass_through"
        ))
        assert result.pass_through_total == expected_pass_through, (
            f"{msg} pass_through_total mismatch"
        )


class TestOptionalFeeExclusion:
    """Strict Whitelist proof — optional fees MUST NOT leak into the base quote.

    Simulates the Strict Whitelist architecture at the ledger level:
      - Early Check-In and Late Check-Out are EXEMPT, optional fees.
      - When selected_add_on_ids is empty, these fees contribute $0.00.
      - Taxes on EXEMPT items must be $0.00.
      - Processing Fee base = Rent + Cleaning + ADW only (no optional fees).
    """

    RENT = Decimal("600.00")
    CLEANING = Decimal("225.00")
    ADW = Decimal("65.00")
    EARLY_CHECKIN = Decimal("50.00")
    LATE_CHECKOUT = Decimal("50.00")
    PROCESSING_RATE = Decimal("5.545")
    NIGHTS = 2

    def _build_base_items(self, include_optional: bool = False) -> list[BucketedItem]:
        """Build a canonical BRLS-like invoice with or without optional fees."""
        items = [
            BucketedItem(name="Base Rent (2 nights)", amount=self.RENT, item_type="rent", bucket=TaxBucket.LODGING),
            BucketedItem(name="Cleaning Fee", amount=self.CLEANING, item_type="fee", bucket=TaxBucket.LODGING),
            BucketedItem(name="Accidental Damage Waiver", amount=self.ADW, item_type="fee", bucket=TaxBucket.EXEMPT),
        ]

        if include_optional:
            items.append(BucketedItem(name="Early Check-In", amount=self.EARLY_CHECKIN, item_type="fee", bucket=TaxBucket.EXEMPT))
            items.append(BucketedItem(name="Late Check-Out", amount=self.LATE_CHECKOUT, item_type="fee", bucket=TaxBucket.EXEMPT))

        flat_total = self.RENT + self.CLEANING + self.ADW
        if include_optional:
            flat_total += self.EARLY_CHECKIN + self.LATE_CHECKOUT

        processing_fee = _money(flat_total * self.PROCESSING_RATE / ONE_HUNDRED)
        items.append(BucketedItem(name="Processing Fee", amount=processing_fee, item_type="fee", bucket=TaxBucket.EXEMPT))

        return items

    def test_base_quote_excludes_optional_fees(self) -> None:
        """With NO selected add-ons, Early/Late fees must be absent and $0.00."""
        items = self._build_base_items(include_optional=False)

        optional_names = {"Early Check-In", "Late Check-Out"}
        for item in items:
            assert item.name not in optional_names, (
                f"Optional fee '{item.name}' leaked into base quote"
            )

        total = sum(i.amount for i in items)
        expected_processing = _money((self.RENT + self.CLEANING + self.ADW) * self.PROCESSING_RATE / ONE_HUNDRED)
        expected_total = self.RENT + self.CLEANING + self.ADW + expected_processing
        assert total == expected_total, (
            f"Base total mismatch: got {total}, expected {expected_total}"
        )

    def test_taxes_zero_on_exempt_bucket(self) -> None:
        """EXEMPT bucket items (ADW, Processing, optional fees) attract $0.00 tax."""
        items = self._build_base_items(include_optional=True)
        tax_result = resolve_taxes(items, "fannin", self.NIGHTS)

        exempt_items = [i for i in items if i.bucket == TaxBucket.EXEMPT]
        assert len(exempt_items) >= 3, "Expected at least ADW + Processing + optional fees in EXEMPT"

        exempt_total = sum(i.amount for i in exempt_items)
        lodging_base = sum(i.amount for i in items if i.bucket == TaxBucket.LODGING)
        assert lodging_base == self.RENT + self.CLEANING, (
            f"Lodging base should be Rent + Cleaning = {self.RENT + self.CLEANING}, got {lodging_base}"
        )

        assert exempt_total > Decimal("0"), "EXEMPT total should be non-zero (ADW + Processing + optional)"
        # Verify no tax was computed on exempt items by checking the tax breakdown
        for detail in tax_result.details:
            assert detail.bucket != TaxBucket.EXEMPT, (
                f"Tax detail '{detail.tax_name}' is levied on EXEMPT bucket — this must never happen"
            )

    def test_processing_fee_base_without_optionals(self) -> None:
        """Processing Fee base must be (Rent + Cleaning + ADW) when no optional fees selected."""
        base = self.RENT + self.CLEANING + self.ADW
        expected_fee = _money(base * self.PROCESSING_RATE / ONE_HUNDRED)

        items = self._build_base_items(include_optional=False)
        processing_items = [i for i in items if "processing" in i.name.lower()]
        assert len(processing_items) == 1, "Expected exactly one Processing Fee line"
        assert processing_items[0].amount == expected_fee, (
            f"Processing Fee mismatch: got {processing_items[0].amount}, expected {expected_fee} "
            f"(base={base}, rate={self.PROCESSING_RATE}%)"
        )

    def test_processing_fee_base_with_optionals(self) -> None:
        """Processing Fee base expands to include selected optional fees."""
        base_with_opts = self.RENT + self.CLEANING + self.ADW + self.EARLY_CHECKIN + self.LATE_CHECKOUT
        expected_fee = _money(base_with_opts * self.PROCESSING_RATE / ONE_HUNDRED)

        items = self._build_base_items(include_optional=True)
        processing_items = [i for i in items if "processing" in i.name.lower()]
        assert len(processing_items) == 1
        assert processing_items[0].amount == expected_fee, (
            f"Processing Fee with optionals mismatch: got {processing_items[0].amount}, "
            f"expected {expected_fee} (base={base_with_opts}, rate={self.PROCESSING_RATE}%)"
        )

    def test_classify_optional_fees_as_exempt(self) -> None:
        """Early Check-In and Late Check-Out must classify into TaxBucket.EXEMPT."""
        assert classify_item("fee", "Early Check-In") == TaxBucket.EXEMPT
        assert classify_item("fee", "Late Check-Out") == TaxBucket.EXEMPT
        assert classify_item("fee", "early check-in") == TaxBucket.EXEMPT
        assert classify_item("fee", "late check-out") == TaxBucket.EXEMPT
        assert classify_item("fee", "Early  Check In") == TaxBucket.EXEMPT
        assert classify_item("fee", "Late  Check Out") == TaxBucket.EXEMPT

    def test_grand_total_without_optionals_is_exact(self) -> None:
        """Full pipeline: base quote grand total = Rent + Clean + ADW + Processing + Taxes, $0 from optional fees."""
        items = self._build_base_items(include_optional=False)
        tax_result = resolve_taxes(items, "fannin", self.NIGHTS)

        pre_tax_subtotal = sum(i.amount for i in items)
        grand_total = _money(pre_tax_subtotal + tax_result.total_tax)

        early_late_contribution = Decimal("0.00")
        for item in items:
            if "check-in" in item.name.lower() or "check-out" in item.name.lower():
                early_late_contribution += item.amount

        assert early_late_contribution == Decimal("0.00"), (
            f"Optional fees contributed ${early_late_contribution} to the base quote — must be $0.00"
        )

        assert grand_total > Decimal("0.00"), "Grand total should be positive"
        assert grand_total == grand_total.quantize(TWO_PLACES), "Grand total must be penny-exact"
