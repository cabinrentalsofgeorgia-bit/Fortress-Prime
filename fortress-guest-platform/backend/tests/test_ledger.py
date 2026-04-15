"""
Ledger Test Suite — 2026 calibrated, penny-perfect scenarios.

Tax Rates (2026):
  All jurisdictions:  State 4% + Local 3% = 7% combined Sales Tax
  Fannin (Unincorp):  6% Lodging | 0.206% Hospitality | $5/night DOT
  Blue Ridge (City):  8% Lodging | $5/night DOT
  Gilmer:             8% Lodging | $5/night DOT
  Union:              5% Lodging | $5/night DOT

Bucket rules (legacy-aligned):
  LODGING: Rent, Cleaning, Pet Fees, Extra Guest
  EXEMPT:  ADW, Processing Fee, Early Check-In, Late Check-Out, Deposits
  GOODS:   Firewood
  SERVICE: Fishing, Concierge

If the math is off by even $0.01 on ANY scenario, the test fails.
"""

from decimal import Decimal

from backend.services.ledger import (
    BucketedItem,
    TaxBucket,
    classify_item,
    resolve_taxes,
    calculate_owner_payout,
    OwnerPayoutBreakdown,
)

D = Decimal


def _assert_money_eq(actual: Decimal, expected: Decimal, label: str) -> None:
    assert actual == expected, f"{label}: expected ${expected} but got ${actual} (diff: ${actual - expected})"


# ──────────────────────────────────────────────────────────────────────────
# Scenario 1: 2 nights in Fannin, lodging only ($325/night + $175 cleaning)
# Lodging base = $650 + $175 = $825
# State Sales:   $825 × 4%     = $33.00
# County Sales:  $825 × 3%     = $24.75
# Lodging Tax:   $825 × 6%     = $49.50
# Hospitality:   $825 × 0.206% = $1.70
# DOT Fee:       $5 × 2        = $10.00
# Total Tax:                      $118.95
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_01_fannin_2_nights_lodging_only():
    items = [
        BucketedItem(name="Base Rent", amount=D("650.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "Fannin", nights=2)
    _assert_money_eq(result.state_sales_tax, D("33.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("24.75"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("49.50"), "lodging_tax")
    _assert_money_eq(result.hospitality_tax, D("1.70"), "hospitality_tax")
    _assert_money_eq(result.dot_fee, D("10.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("118.95"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 2: 3 nights in Gilmer, lodging + firewood
# Lodging: $350×3 + $175 = $1225
# Firewood: $40
# State Sales on Lodging: $1225 × 4% = $49.00
# County Sales on Lodging: $1225 × 3% = $36.75
# Lodging Tax: $1225 × 8% = $98.00
# DOT: $5 × 3 = $15.00
# State Sales on Goods: $40 × 4% = $1.60
# County Sales on Goods: $40 × 3% = $1.20
# Total Tax: $201.55
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_02_gilmer_3_nights_with_firewood():
    items = [
        BucketedItem(name="Base Rent", amount=D("1050.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Firewood Bundle", amount=D("40.00"), item_type="addon", bucket=TaxBucket.GOODS),
    ]
    result = resolve_taxes(items, "Gilmer", nights=3)
    _assert_money_eq(result.state_sales_tax, D("50.60"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("37.95"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("98.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("15.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("201.55"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 3: 2 nights in Union, lodging + guided fishing (service = no tax)
# Lodging: $400×2 + $150 = $950
# Guided fishing: $250 (SERVICE — no tax)
# State Sales: $950 × 4% = $38.00
# County Sales: $950 × 3% = $28.50
# Lodging Tax: $950 × 5% = $47.50
# DOT: $5 × 2 = $10.00
# Total Tax: $124.00
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_03_union_2_nights_with_fishing_guide():
    items = [
        BucketedItem(name="Base Rent", amount=D("800.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("150.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Guided Fly Fishing", amount=D("250.00"), item_type="addon", bucket=TaxBucket.SERVICE),
    ]
    result = resolve_taxes(items, "Union", nights=2)
    _assert_money_eq(result.state_sales_tax, D("38.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("28.50"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("47.50"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("10.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("124.00"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 4: 1 night in Fannin, minimum stay ($325 + $175 cleaning)
# Lodging: $500
# State Sales: $500 × 4% = $20.00
# County Sales: $500 × 3% = $15.00
# Lodging Tax: $500 × 6% = $30.00
# Hospitality: $500 × 0.206% = $1.03
# DOT: $5 × 1 = $5.00
# Total Tax: $71.03
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_04_fannin_1_night_minimum():
    items = [
        BucketedItem(name="Base Rent", amount=D("325.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "Fannin", nights=1)
    _assert_money_eq(result.state_sales_tax, D("20.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("15.00"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("30.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("5.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("71.03"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 5: 7 nights in Fannin, holiday rate + extra guest fee + pet deposit
# Rent: $6293 | Cleaning: $225 | Extra Guest: $350 | Pet Clean: $150
# Pet Deposit: $250 (EXEMPT)
# Lodging base: $6293 + $225 + $350 + $150 = $7018
# State Sales: $7018 × 4% = $280.72
# County Sales: $7018 × 3% = $210.54
# Lodging Tax: $7018 × 6% = $421.08
# Hospitality: $7018 × 0.206% = $14.46
# DOT: $5 × 7 = $35.00
# Total Tax: $961.80
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_05_fannin_7_nights_holiday_with_extras():
    items = [
        BucketedItem(name="Base Rent", amount=D("6293.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("225.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Extra Guest Fee", amount=D("350.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Pet Cleaning Fee", amount=D("150.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Refundable Pet Deposit", amount=D("250.00"), item_type="deposit", bucket=TaxBucket.EXEMPT),
    ]
    result = resolve_taxes(items, "Fannin", nights=7)
    _assert_money_eq(result.state_sales_tax, D("280.72"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("210.54"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("421.08"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("35.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("961.80"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 6: 3 nights in Gilmer, lodging + fishing guide + firewood
# Lodging: $375×3 + $175 = $1300
# Firewood: $40 (GOODS) | Fishing: $300 (SERVICE — $0 tax)
# State Sales: ($1300 × 4%) + ($40 × 4%) = $52.00 + $1.60 = $53.60
# County Sales: ($1300 × 3%) + ($40 × 3%) = $39.00 + $1.20 = $40.20
# Lodging Tax: $1300 × 8% = $104.00
# DOT: $5 × 3 = $15.00
# Total Tax: $212.80
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_06_gilmer_mixed_buckets():
    items = [
        BucketedItem(name="Base Rent", amount=D("1125.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Firewood", amount=D("40.00"), item_type="addon", bucket=TaxBucket.GOODS),
        BucketedItem(name="Guided Fishing", amount=D("300.00"), item_type="addon", bucket=TaxBucket.SERVICE),
    ]
    result = resolve_taxes(items, "Gilmer", nights=3)
    _assert_money_eq(result.state_sales_tax, D("53.60"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("40.20"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("104.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("15.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("212.80"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 7: Service-only booking (fishing only, no lodging) — $0 tax
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_07_service_only_zero_tax():
    items = [
        BucketedItem(name="Guided Fly Fishing Full Day", amount=D("500.00"), item_type="addon", bucket=TaxBucket.SERVICE),
    ]
    result = resolve_taxes(items, "Fannin", nights=0)
    _assert_money_eq(result.total_tax, D("0.00"), "total_tax")
    _assert_money_eq(result.state_sales_tax, D("0.00"), "state_sales_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 8: 5 nights in Union, lodging with discount
# Rent: $1750 | Cleaning: $175 | Discount: -$200 (LODGING bucket)
# Lodging base: $1750 + $175 - $200 = $1725
# State Sales: $1725 × 4% = $69.00
# County Sales: $1725 × 3% = $51.75
# Lodging Tax: $1725 × 5% = $86.25
# DOT: $5 × 5 = $25.00
# Total Tax: $232.00
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_08_union_5_nights_with_discount():
    items = [
        BucketedItem(name="Base Rent", amount=D("1750.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Early Bird Discount", amount=D("-200.00"), item_type="discount", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "Union", nights=5)
    _assert_money_eq(result.state_sales_tax, D("69.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("51.75"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("86.25"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("25.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("232.00"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 9: Odd cents — 4 nights in Fannin, $399/night
# Rent: $1596 | Cleaning: $175
# Lodging base: $1771
# State Sales: $1771 × 4% = $70.84
# County Sales: $1771 × 3% = $53.13
# Lodging Tax: $1771 × 6% = $106.26
# Hospitality: $1771 × 0.206% = $3.65
# DOT: $5 × 4 = $20.00
# Total Tax: $253.88
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_09_fannin_odd_cents():
    items = [
        BucketedItem(name="Base Rent", amount=D("1596.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "Fannin", nights=4)
    _assert_money_eq(result.state_sales_tax, D("70.84"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("53.13"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("106.26"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("20.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("253.88"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 10: Default county fallback (unknown county → Fannin rates)
# 2 nights, $350/night + $175 cleaning
# Lodging base: $875
# State Sales: $875 × 4% = $35.00
# County Sales: $875 × 3% = $26.25  (Fannin default)
# Lodging Tax: $875 × 6% = $52.50
# Hospitality: $875 × 0.206% = $1.80
# DOT: $5 × 2 = $10.00
# Total Tax: $125.55
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_10_unknown_county_defaults_to_fannin():
    items = [
        BucketedItem(name="Base Rent", amount=D("700.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("175.00"), item_type="fee", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "SomeUnknownCounty", nights=2)
    _assert_money_eq(result.state_sales_tax, D("35.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("26.25"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("52.50"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("10.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("125.55"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 11: Blue Ridge (City) — 3 nights, $425/night + $200 cleaning
# Lodging base: $1275 + $200 = $1475
# State Sales: $1475 × 4% = $59.00
# County Sales: $1475 × 3% = $44.25
# Lodging Tax: $1475 × 8% = $118.00
# DOT: $5 × 3 = $15.00
# Total Tax: $236.25
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_11_blue_ridge_city_3_nights():
    items = [
        BucketedItem(name="Base Rent", amount=D("1275.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("200.00"), item_type="fee", bucket=TaxBucket.LODGING),
    ]
    result = resolve_taxes(items, "Blue Ridge", nights=3)
    _assert_money_eq(result.state_sales_tax, D("59.00"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("44.25"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("118.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("15.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("236.25"), "total_tax")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 12: Blue Ridge vs Fannin comparison — same base, different lodging
# $1000 lodging, 2 nights
# Blue Ridge: State $40 + County $30 + Lodging $80 + DOT $10 = $160
# Fannin:     State $40 + County $30 + Lodging $60 + Hospitality $2.06 + DOT $10 = $142.06
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_12_blue_ridge_vs_fannin_lodging_rate_diff():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
    ]
    br = resolve_taxes(items, "Blue Ridge", nights=2)
    fn = resolve_taxes(items, "Fannin", nights=2)

    _assert_money_eq(br.state_sales_tax, D("40.00"), "BR state")
    _assert_money_eq(br.lodging_tax, D("80.00"), "BR lodging")
    _assert_money_eq(br.total_tax, D("160.00"), "BR total")

    _assert_money_eq(fn.state_sales_tax, D("40.00"), "FN state")
    _assert_money_eq(fn.lodging_tax, D("60.00"), "FN lodging")
    _assert_money_eq(fn.total_tax, D("142.06"), "FN total")

    assert br.total_tax > fn.total_tax, "Blue Ridge should have higher total tax than Fannin unincorporated"


# ──────────────────────────────────────────────────────────────────────────
# Bucket classification tests
# ──────────────────────────────────────────────────────────────────────────
def test_classify_firewood_as_goods():
    assert classify_item("addon", "Firewood Bundle") == TaxBucket.GOODS


def test_classify_fishing_as_service():
    assert classify_item("addon", "Guided Fly Fishing") == TaxBucket.SERVICE


def test_classify_rent_as_lodging():
    assert classify_item("rent", "Base Rent") == TaxBucket.LODGING


def test_classify_deposit_as_exempt():
    assert classify_item("deposit", "Refundable Pet Deposit") == TaxBucket.EXEMPT


def test_classify_cleaning_fee_as_lodging():
    assert classify_item("fee", "Cleaning Fee") == TaxBucket.LODGING


def test_classify_damage_waiver_as_exempt():
    assert classify_item("fee", "Accidental Damage Waiver") == TaxBucket.EXEMPT


def test_classify_processing_fee_as_exempt():
    assert classify_item("fee", "Processing Fee") == TaxBucket.EXEMPT


def test_classify_adw_substring_as_exempt():
    assert classify_item("fee", "ADW - Above the Timberline") == TaxBucket.EXEMPT


# ──────────────────────────────────────────────────────────────────────────
# Regex classifier edge-case tests
# ──────────────────────────────────────────────────────────────────────────

def test_classify_mixed_case_damage_waiver():
    assert classify_item("fee", "ACCIDENTAL DAMAGE WAIVER") == TaxBucket.EXEMPT
    assert classify_item("fee", "accidental damage waiver") == TaxBucket.EXEMPT
    assert classify_item("fee", "Accidental Damage Waiver") == TaxBucket.EXEMPT


def test_classify_name_with_extra_whitespace():
    assert classify_item("fee", "  Processing Fee  ") == TaxBucket.EXEMPT
    assert classify_item("fee", "  Cleaning Fee  ") == TaxBucket.LODGING


def test_classify_name_with_property_suffix():
    assert classify_item("fee", "Cleaning Fee - above-the-timberline") == TaxBucket.LODGING
    assert classify_item("fee", "Damage Waiver - creekside-green") == TaxBucket.EXEMPT
    assert classify_item("addon", "Firewood Bundle - skyfall") == TaxBucket.GOODS


def test_classify_fire_wood_with_space():
    assert classify_item("addon", "Fire Wood") == TaxBucket.GOODS
    assert classify_item("addon", "fire wood bundle") == TaxBucket.GOODS


def test_classify_concierge_as_service():
    assert classify_item("addon", "Concierge Package") == TaxBucket.SERVICE


def test_classify_fishing_guide_as_service():
    assert classify_item("addon", "Fishing Guide Half Day") == TaxBucket.SERVICE


def test_classify_refund_as_exempt():
    assert classify_item("fee", "Guest Refund") == TaxBucket.EXEMPT


def test_classify_security_deposit_by_regex():
    assert classify_item("fee", "Security Deposit") == TaxBucket.EXEMPT


def test_classify_pet_fee_as_lodging():
    assert classify_item("fee", "Pet Cleaning Fee") == TaxBucket.LODGING


def test_classify_extra_guest_as_lodging():
    assert classify_item("fee", "Extra Guest Fee (2 guests × 3 nights)") == TaxBucket.LODGING


def test_classify_unknown_falls_to_type_default():
    assert classify_item("rent", "Some Unknown Item") == TaxBucket.LODGING
    assert classify_item("deposit", "Some Unknown Deposit") == TaxBucket.EXEMPT
    assert classify_item("fee", "Some Random Fee") == TaxBucket.LODGING


def test_classify_exempt_keyword_in_longer_name():
    assert classify_item("fee", "Standard Administrative Fee - Q4") == TaxBucket.EXEMPT
    assert classify_item("fee", "Booking Processing Fee (Non-Refundable)") == TaxBucket.EXEMPT


# ──────────────────────────────────────────────────────────────────────────
# Scenario 13: Full fee breakdown — $1,000 lodging + 3% Processing + $60 ADW
#   Fannin, 2 nights
#
# LODGING bucket ($1,000):
#   State Sales: $1,000 × 4%  = $40.00
#   County Sales: $1,000 × 3%  = $30.00
#   Lodging Tax:  $1,000 × 6%  = $60.00
#   Hospitality:  $1,000 × 0.206% = $2.06
#   DOT:          $5 × 2       = $10.00
#
# ADMIN bucket ($30 + $60 = $90):
#   State Sales: $90 × 4% = $3.60
#   County Sales: $90 × 3% = $2.70
#   NO Lodging Tax
#   NO DOT Fee
#
# Total State Sales: $40.00 + $3.60 = $43.60
# Total County Sales: $30.00 + $2.70 = $32.70
# Total Lodging Tax: $60.00
# Total DOT: $10.00
# Grand Total Tax: $148.36
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_13_full_fee_breakdown_with_admin_fees():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Processing Fee", amount=D("30.00"), item_type="fee", bucket=TaxBucket.ADMIN),
        BucketedItem(name="Accidental Damage Waiver", amount=D("60.00"), item_type="fee", bucket=TaxBucket.ADMIN),
    ]
    result = resolve_taxes(items, "Fannin", nights=2)

    _assert_money_eq(result.state_sales_tax, D("43.60"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("32.70"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("60.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("10.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("148.36"), "total_tax")

    admin_details = [d for d in result.details if d.bucket == TaxBucket.ADMIN]
    assert len(admin_details) == 2, f"Expected 2 ADMIN detail lines, got {len(admin_details)}"

    for d in admin_details:
        _assert_money_eq(d.taxable_base, D("90.00"), f"{d.tax_name} taxable_base")

    lodging_details = [d for d in result.details if d.bucket == TaxBucket.LODGING]
    for d in lodging_details:
        if "Lodging Tax" in d.tax_name:
            _assert_money_eq(d.taxable_base, D("1000.00"), "lodging_tax_base_must_exclude_admin")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 14: Full realistic booking — rent + cleaning + ADW + processing
#   Fannin, 3 nights @ $350/night, $200 cleaning, $65 ADW, $81 processing
#
# LODGING: $1050 + $200 = $1250
#   State: $1250 × 4% = $50.00
#   County: $1250 × 3% = $37.50
#   Lodging: $1250 × 6% = $75.00
#   Hospitality: $1250 × 0.206% = $2.58
#   DOT: $5 × 3 = $15.00
#
# ADMIN: $65 + $81 = $146
#   State: $146 × 4% = $5.84
#   County: $146 × 3% = $4.38
#
# Total State: $55.84 | Total County: $41.88 | Lodging: $75.00 | DOT: $15.00
# Total Tax: $190.30
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_14_realistic_booking_with_admin_fees():
    items = [
        BucketedItem(name="Base Rent", amount=D("1050.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("200.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Accidental Damage Waiver", amount=D("65.00"), item_type="fee", bucket=TaxBucket.ADMIN),
        BucketedItem(name="Processing Fee", amount=D("81.00"), item_type="fee", bucket=TaxBucket.ADMIN),
    ]
    result = resolve_taxes(items, "Fannin", nights=3)

    _assert_money_eq(result.state_sales_tax, D("55.84"), "state_sales_tax")
    _assert_money_eq(result.county_sales_tax, D("41.88"), "county_sales_tax")
    _assert_money_eq(result.lodging_tax, D("75.00"), "lodging_tax")
    _assert_money_eq(result.dot_fee, D("15.00"), "dot_fee")
    _assert_money_eq(result.total_tax, D("190.30"), "total_tax")


# ══════════════════════════════════════════════════════════════════════════
# Owner Payout Tests — Fiduciary hardening
# ══════════════════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────────────────
# Scenario 15: Owner payout accuracy — $1,000 Rent, $225 Cleaning, $60 ADW
#   25% Commission. Model A: CC processing absorbed by company, not deducted.
#
#   Commissionable:     $1,000 (Rent only)
#   Pass-through:       $225 (Cleaning) + $60 (ADW) = $285
#   Commission:         $1,000 × 25% = $250.00
#   Net Owner Payout:   $1,000 - $250 = $750.00
#   CC Processing:      $0.00 (absorbed by company — Model A)
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_15_owner_payout_accuracy():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("225.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Accidental Damage Waiver", amount=D("60.00"), item_type="fee", bucket=TaxBucket.ADMIN),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.gross_revenue, D("1000.00"), "gross_revenue")
    _assert_money_eq(result.pass_through_total, D("285.00"), "pass_through_total")
    _assert_money_eq(result.commission_amount, D("250.00"), "commission_amount")
    _assert_money_eq(result.total_collected, D("1285.00"), "total_collected")
    _assert_money_eq(result.cc_processing_fee, D("0.00"), "cc_processing_fee (Model A: $0)")
    _assert_money_eq(result.net_owner_payout, D("750.00"), "net_owner_payout")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 16: Owner payout with pet fees — pet fees ARE commissionable
#   $800 Rent, $100 Pet Fee, $200 Cleaning, $65 ADW, $81 Processing Fee
#   Commissionable: $800 + $100 = $900
#   Pass-through:   $200 + $65 + $81 = $346
#   Commission:     $900 × 25% = $225.00
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_16_owner_payout_with_pet_fees():
    items = [
        BucketedItem(name="Base Rent", amount=D("800.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Pet Fee", amount=D("100.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("200.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Accidental Damage Waiver", amount=D("65.00"), item_type="fee", bucket=TaxBucket.ADMIN),
        BucketedItem(name="Processing Fee", amount=D("81.00"), item_type="fee", bucket=TaxBucket.ADMIN),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.gross_revenue, D("900.00"), "gross_revenue")
    _assert_money_eq(result.pass_through_total, D("346.00"), "pass_through_total")
    _assert_money_eq(result.commission_amount, D("225.00"), "commission_amount")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 17: Taxes are pass-through — never commissionable
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_17_taxes_are_pass_through():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="State Sales Tax", amount=D("40.00"), item_type="tax", bucket=TaxBucket.LODGING),
        BucketedItem(name="County Lodging Tax", amount=D("60.00"), item_type="tax", bucket=TaxBucket.LODGING),
        BucketedItem(name="GA DOT Fee", amount=D("10.00"), item_type="tax", bucket=TaxBucket.LODGING),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.gross_revenue, D("1000.00"), "gross_revenue")
    _assert_money_eq(result.pass_through_total, D("110.00"), "pass_through_total")
    _assert_money_eq(result.commission_amount, D("250.00"), "commission_amount")

    pass_through_names = [d.name for d in result.details if d.category == "pass_through"]
    assert "State Sales Tax" in pass_through_names
    assert "County Lodging Tax" in pass_through_names
    assert "GA DOT Fee" in pass_through_names


# ──────────────────────────────────────────────────────────────────────────
# Scenario 18: Deposits are pass-through
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_18_deposits_are_pass_through():
    items = [
        BucketedItem(name="Base Rent", amount=D("500.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Refundable Pet Deposit", amount=D("250.00"), item_type="deposit", bucket=TaxBucket.EXEMPT),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.gross_revenue, D("500.00"), "gross_revenue")
    _assert_money_eq(result.pass_through_total, D("250.00"), "pass_through_total")
    _assert_money_eq(result.commission_amount, D("125.00"), "commission_amount")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 19: CC processing fee is always zero (Model A)
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_19_cc_processing_always_zero_model_a():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.net_owner_payout, D("750.00"), "net_owner_payout")
    _assert_money_eq(result.cc_processing_fee, D("0.00"), "cc_processing_fee")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 20: Full realistic booking payout — rent + cleaning + ADW +
#   processing + tax + deposit, 25% commission. Model A: CC absorbed.
#   $1,000 Rent, $225 Cleaning, $60 ADW, $81 Processing, $187.72 Tax
#   Commissionable: $1,000
#   Pass-through:   $225 + $60 + $81 + $187.72 = $553.72
#   Commission:     $250.00
#   CC Processing:  $0.00 (Model A: absorbed by company)
#   Net Owner:      $1,000 - $250 = $750.00
# ──────────────────────────────────────────────────────────────────────────
def test_scenario_20_full_realistic_owner_payout():
    items = [
        BucketedItem(name="Base Rent", amount=D("1000.00"), item_type="rent", bucket=TaxBucket.LODGING),
        BucketedItem(name="Cleaning Fee", amount=D("225.00"), item_type="fee", bucket=TaxBucket.LODGING),
        BucketedItem(name="Accidental Damage Waiver", amount=D("60.00"), item_type="fee", bucket=TaxBucket.ADMIN),
        BucketedItem(name="Processing Fee", amount=D("81.00"), item_type="fee", bucket=TaxBucket.ADMIN),
        BucketedItem(name="Taxes", amount=D("187.72"), item_type="tax", bucket=TaxBucket.LODGING),
    ]
    result = calculate_owner_payout(items, commission_rate=D("25.00"))

    _assert_money_eq(result.gross_revenue, D("1000.00"), "gross_revenue")
    _assert_money_eq(result.pass_through_total, D("553.72"), "pass_through_total")
    _assert_money_eq(result.commission_amount, D("250.00"), "commission_amount")
    _assert_money_eq(result.total_collected, D("1553.72"), "total_collected")
    _assert_money_eq(result.cc_processing_fee, D("0.00"), "cc_processing_fee (Model A)")
    _assert_money_eq(result.net_owner_payout, D("750.00"), "net_owner_payout")


# ──────────────────────────────────────────────────────────────────────────
# B1 confirmation: Model A — no CC processing deduction
# $1,615 rent at 30% commission must produce exactly $1,130.50 net
# ──────────────────────────────────────────────────────────────────────────
def test_owner_payout_no_processing_fee_deduction():
    """
    Model A (Phase B): owner net = rent × (1 - commission_rate).
    $1,615 rent at 30% commission = $1,615 × 0.70 = $1,130.50.
    CC processing fee must be $0.00 (absorbed by the company).
    """
    from decimal import Decimal
    items = [
        BucketedItem(name="Base Rent", amount=D("1615.00"), item_type="rent", bucket=TaxBucket.LODGING),
    ]
    result = calculate_owner_payout(items, commission_rate=D("30.00"))

    _assert_money_eq(result.gross_revenue,    D("1615.00"), "gross_revenue")
    _assert_money_eq(result.commission_amount, D("484.50"),  "commission_amount (30%)")
    _assert_money_eq(result.cc_processing_fee, D("0.00"),    "cc_processing_fee (Model A: $0)")
    _assert_money_eq(result.net_owner_payout,  D("1130.50"), "net_owner_payout")
