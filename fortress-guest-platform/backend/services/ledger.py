"""
Multi-Bucket Tax Resolver — FinTech-grade tax engine for North Georgia.

Every line item on a guest invoice falls into exactly one tax bucket.
Each bucket defines which taxes apply and at what rates, based on
the property's county/city. This eliminates the guesswork from monthly
tax filings: the system knows exactly how much is owed to the State
of Georgia, to each county, and to the GA DOT.

Tax Buckets:
  LODGING  — Rent, Cleaning, Extra Guest Fees
             → Sales Tax (7%) + County/City Lodging Tax + GA DOT Fee ($5/night)
  EXEMPT   — ADW, Processing Fee, Early Check-In, Late Check-Out
             → NO TAX (legacy-verified: these are non-taxable pass-throughs)
  GOODS    — Firewood, physical supplies sold to guests
             → Sales Tax (7%) ONLY
  SERVICE  — Guided Fishing, concierge services
             → NO TAX (services exempt under GA code)
  EXEMPT   — Refundable deposits, discounts
             → NO TAX

Tax Rates (Georgia, calibrated 2026):
  All jurisdictions:  State 4% + Local 3% = 7% combined Sales Tax
  Fannin (Unincorp):  6% Lodging | $5/night DOT
  Blue Ridge (City):  8% Lodging | $5/night DOT
  Gilmer:             8% Lodging | $5/night DOT
  Union:              5% Lodging | $5/night DOT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Sequence

import structlog
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

predict_logger = structlog.get_logger(service="predictive_ledger")

TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class TaxBucket(str, Enum):
    LODGING = "lodging"
    ADMIN = "admin"
    GOODS = "goods"
    SERVICE = "service"
    EXEMPT = "exempt"


@dataclass(frozen=True)
class CountyTaxRates:
    county: str
    state_sales_rate: Decimal
    county_sales_rate: Decimal
    lodging_tax_rate: Decimal
    dot_nightly_fee: Decimal
    hospitality_tax_rate: Decimal = Decimal("0.00")

    @property
    def combined_sales_rate(self) -> Decimal:
        return self.state_sales_rate + self.county_sales_rate


COUNTY_RATES: dict[str, CountyTaxRates] = {
    "fannin": CountyTaxRates(
        county="Fannin",
        state_sales_rate=Decimal("4.00"),
        county_sales_rate=Decimal("3.00"),
        lodging_tax_rate=Decimal("6.00"),
        dot_nightly_fee=Decimal("5.00"),
        hospitality_tax_rate=Decimal("0.206"),
    ),
    "blue ridge": CountyTaxRates(
        county="Blue Ridge",
        state_sales_rate=Decimal("4.00"),
        county_sales_rate=Decimal("3.00"),
        lodging_tax_rate=Decimal("8.00"),
        dot_nightly_fee=Decimal("5.00"),
    ),
    "gilmer": CountyTaxRates(
        county="Gilmer",
        state_sales_rate=Decimal("4.00"),
        county_sales_rate=Decimal("3.00"),
        lodging_tax_rate=Decimal("8.00"),
        dot_nightly_fee=Decimal("5.00"),
    ),
    "union": CountyTaxRates(
        county="Union",
        state_sales_rate=Decimal("4.00"),
        county_sales_rate=Decimal("3.00"),
        lodging_tax_rate=Decimal("5.00"),
        dot_nightly_fee=Decimal("5.00"),
    ),
}

DEFAULT_COUNTY = "fannin"


def get_county_rates(county: str | None) -> CountyTaxRates:
    if not county:
        return COUNTY_RATES[DEFAULT_COUNTY]
    key = county.strip().lower()
    return COUNTY_RATES.get(key, COUNTY_RATES[DEFAULT_COUNTY])


ITEM_TYPE_TO_BUCKET: dict[str, TaxBucket] = {
    "rent": TaxBucket.LODGING,
    "fee": TaxBucket.LODGING,
    "addon": TaxBucket.LODGING,
    "deposit": TaxBucket.EXEMPT,
    "discount": TaxBucket.LODGING,
}

@dataclass(frozen=True)
class ClassificationRule:
    pattern: re.Pattern[str]
    bucket: TaxBucket
    priority: int


CLASSIFICATION_RULES: list[ClassificationRule] = [
    ClassificationRule(re.compile(r"deposit|\brefund\b", re.I),                      TaxBucket.EXEMPT,  100),
    ClassificationRule(re.compile(r"waiver|damage|adw|processing|admin", re.I),      TaxBucket.EXEMPT,  90),
    ClassificationRule(re.compile(r"check.?in|check.?out|early.?arr|late.?dep", re.I), TaxBucket.EXEMPT, 85),
    ClassificationRule(re.compile(r"firewood|fire\s*wood", re.I),                    TaxBucket.GOODS,   80),
    ClassificationRule(re.compile(r"fish|guide|concierge", re.I),                    TaxBucket.SERVICE, 70),
    ClassificationRule(re.compile(r"clean|pet|extra.guest", re.I),                   TaxBucket.LODGING, 60),
]


def classify_item(item_type: str, item_name: str) -> TaxBucket:
    """Classify a line item into a tax bucket using regex pattern matching.

    Rules are evaluated in priority order (highest first). The first match wins.
    If no regex matches, falls back to ITEM_TYPE_TO_BUCKET or LODGING default.
    """
    name = item_name.strip()
    for rule in CLASSIFICATION_RULES:
        if rule.pattern.search(name):
            return rule.bucket
    return ITEM_TYPE_TO_BUCKET.get(item_type, TaxBucket.LODGING)


@dataclass
class TaxLineDetail:
    tax_name: str
    tax_rate: Decimal
    taxable_base: Decimal
    amount: Decimal
    bucket: TaxBucket


@dataclass
class LedgerTaxBreakdown:
    state_sales_tax: Decimal = Decimal("0.00")
    county_sales_tax: Decimal = Decimal("0.00")
    lodging_tax: Decimal = Decimal("0.00")
    hospitality_tax: Decimal = Decimal("0.00")
    dot_fee: Decimal = Decimal("0.00")
    total_tax: Decimal = Decimal("0.00")
    details: list[TaxLineDetail] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "state_sales_tax": float(self.state_sales_tax),
            "county_sales_tax": float(self.county_sales_tax),
            "lodging_tax": float(self.lodging_tax),
            "hospitality_tax": float(self.hospitality_tax),
            "dot_fee": float(self.dot_fee),
            "total_tax": float(self.total_tax),
            "details": [
                {
                    "tax_name": d.tax_name,
                    "tax_rate": float(d.tax_rate),
                    "taxable_base": float(d.taxable_base),
                    "amount": float(d.amount),
                    "bucket": d.bucket.value,
                }
                for d in self.details
            ],
        }


@dataclass
class BucketedItem:
    name: str
    amount: Decimal
    item_type: str
    bucket: TaxBucket


@dataclass(frozen=True)
class ClassificationResult:
    bucket: TaxBucket
    is_refundable: bool
    refund_policy: str


def _refund_policy_for(bucket: TaxBucket, item_type: str) -> tuple[bool, str]:
    """Derive refundability from tax bucket and item type.

    Deposits are always refundable regardless of bucket.
    Taxes follow the refund status of their base item.
    EXEMPT and ADMIN items (ADW, Processing Fee, etc.) are non-refundable.
    Everything else (LODGING, GOODS, SERVICE) is refundable by default.
    """
    if item_type == "deposit":
        return True, "full"
    if item_type == "tax":
        return False, "follows_base"
    if bucket in (TaxBucket.EXEMPT, TaxBucket.ADMIN):
        return False, "none"
    return True, "full"


def classify_item_full(item_type: str, item_name: str) -> ClassificationResult:
    """Classify a line item into a tax bucket with refundability metadata."""
    bucket = classify_item(item_type, item_name)
    is_refundable, refund_policy = _refund_policy_for(bucket, item_type)
    return ClassificationResult(
        bucket=bucket,
        is_refundable=is_refundable,
        refund_policy=refund_policy,
    )


def resolve_taxes(
    items: Sequence[BucketedItem],
    county: str | None,
    nights: int,
) -> LedgerTaxBreakdown:
    """
    Compute the exact tax breakdown for a set of line items.

    Returns a LedgerTaxBreakdown with per-tax-authority amounts and
    per-line detail records for full audit transparency.
    """
    rates = get_county_rates(county)
    breakdown = LedgerTaxBreakdown()

    lodging_base = Decimal("0.00")
    admin_base = Decimal("0.00")
    goods_base = Decimal("0.00")

    for item in items:
        if item.bucket == TaxBucket.LODGING:
            lodging_base += item.amount
        elif item.bucket == TaxBucket.ADMIN:
            admin_base += item.amount
        elif item.bucket == TaxBucket.GOODS:
            goods_base += item.amount

    # --- LODGING bucket taxes ---
    if lodging_base > Decimal("0.00"):
        state_on_lodging = _money(lodging_base * rates.state_sales_rate / ONE_HUNDRED)
        breakdown.state_sales_tax += state_on_lodging
        breakdown.details.append(TaxLineDetail(
            tax_name=f"GA State Sales Tax ({rates.state_sales_rate}%)",
            tax_rate=rates.state_sales_rate,
            taxable_base=lodging_base,
            amount=state_on_lodging,
            bucket=TaxBucket.LODGING,
        ))

        county_on_lodging = _money(lodging_base * rates.county_sales_rate / ONE_HUNDRED)
        breakdown.county_sales_tax += county_on_lodging
        breakdown.details.append(TaxLineDetail(
            tax_name=f"{rates.county} County Sales Tax ({rates.county_sales_rate}%)",
            tax_rate=rates.county_sales_rate,
            taxable_base=lodging_base,
            amount=county_on_lodging,
            bucket=TaxBucket.LODGING,
        ))

        lodging_tax = _money(lodging_base * rates.lodging_tax_rate / ONE_HUNDRED)
        breakdown.lodging_tax = lodging_tax
        breakdown.details.append(TaxLineDetail(
            tax_name=f"{rates.county} County Lodging Tax ({rates.lodging_tax_rate}%)",
            tax_rate=rates.lodging_tax_rate,
            taxable_base=lodging_base,
            amount=lodging_tax,
            bucket=TaxBucket.LODGING,
        ))

        dot_total = _money(rates.dot_nightly_fee * Decimal(str(nights)))
        breakdown.dot_fee = dot_total
        breakdown.details.append(TaxLineDetail(
            tax_name=f"GA DOT Fee (${rates.dot_nightly_fee}/night × {nights})",
            tax_rate=Decimal("0.00"),
            taxable_base=Decimal(str(nights)),
            amount=dot_total,
            bucket=TaxBucket.LODGING,
        ))

        if rates.hospitality_tax_rate > Decimal("0.00"):
            hosp_tax = _money(lodging_base * rates.hospitality_tax_rate / ONE_HUNDRED)
            breakdown.hospitality_tax = hosp_tax
            breakdown.details.append(TaxLineDetail(
                tax_name=f"{rates.county} Hospitality Tax ({rates.hospitality_tax_rate}%)",
                tax_rate=rates.hospitality_tax_rate,
                taxable_base=lodging_base,
                amount=hosp_tax,
                bucket=TaxBucket.LODGING,
            ))

    # --- ADMIN bucket taxes (sales tax only — NO lodging tax, NO DOT) ---
    if admin_base > Decimal("0.00"):
        state_on_admin = _money(admin_base * rates.state_sales_rate / ONE_HUNDRED)
        breakdown.state_sales_tax += state_on_admin
        breakdown.details.append(TaxLineDetail(
            tax_name=f"GA State Sales Tax on Admin Fees ({rates.state_sales_rate}%)",
            tax_rate=rates.state_sales_rate,
            taxable_base=admin_base,
            amount=state_on_admin,
            bucket=TaxBucket.ADMIN,
        ))

        county_on_admin = _money(admin_base * rates.county_sales_rate / ONE_HUNDRED)
        breakdown.county_sales_tax += county_on_admin
        breakdown.details.append(TaxLineDetail(
            tax_name=f"{rates.county} County Sales Tax on Admin Fees ({rates.county_sales_rate}%)",
            tax_rate=rates.county_sales_rate,
            taxable_base=admin_base,
            amount=county_on_admin,
            bucket=TaxBucket.ADMIN,
        ))

    # --- GOODS bucket taxes (sales tax only) ---
    if goods_base > Decimal("0.00"):
        state_on_goods = _money(goods_base * rates.state_sales_rate / ONE_HUNDRED)
        breakdown.state_sales_tax += state_on_goods
        breakdown.details.append(TaxLineDetail(
            tax_name=f"GA State Sales Tax on Goods ({rates.state_sales_rate}%)",
            tax_rate=rates.state_sales_rate,
            taxable_base=goods_base,
            amount=state_on_goods,
            bucket=TaxBucket.GOODS,
        ))

        county_on_goods = _money(goods_base * rates.county_sales_rate / ONE_HUNDRED)
        breakdown.county_sales_tax += county_on_goods
        breakdown.details.append(TaxLineDetail(
            tax_name=f"{rates.county} County Sales Tax on Goods ({rates.county_sales_rate}%)",
            tax_rate=rates.county_sales_rate,
            taxable_base=goods_base,
            amount=county_on_goods,
            bucket=TaxBucket.GOODS,
        ))

    # SERVICE and EXEMPT buckets: $0 tax — nothing to add

    breakdown.state_sales_tax = _money(breakdown.state_sales_tax)
    breakdown.county_sales_tax = _money(breakdown.county_sales_tax)
    breakdown.lodging_tax = _money(breakdown.lodging_tax)
    breakdown.hospitality_tax = _money(breakdown.hospitality_tax)
    breakdown.dot_fee = _money(breakdown.dot_fee)
    breakdown.total_tax = _money(
        breakdown.state_sales_tax
        + breakdown.county_sales_tax
        + breakdown.lodging_tax
        + breakdown.hospitality_tax
        + breakdown.dot_fee
    )

    return breakdown


# ---------------------------------------------------------------------------
# Owner Payout — Fiduciary-grade split logic
# ---------------------------------------------------------------------------

# Items in these buckets are pass-through: they do NOT enter the commission
# base.  They are collected from the guest, held in trust, and disbursed to
# their respective authorities (tax collectors, cleaning vendors, insurance).
PASS_THROUGH_BUCKETS: frozenset[TaxBucket] = frozenset({
    TaxBucket.ADMIN,    # ADW, Processing Fee
    TaxBucket.EXEMPT,   # Deposits, refunds
})

PASS_THROUGH_TYPES: frozenset[str] = frozenset({
    "tax",
    "deposit",
})

# DEFAULT_COMMISSION_RATE was removed — rates are per-owner, stored in
# owner_payout_accounts.commission_rate. Pass the rate explicitly to
# calculate_owner_payout(). Do not add a default here.
#
# DEFAULT_CC_PROCESSING_RATE / DEFAULT_CC_PROCESSING_FLAT were removed in
# Phase B (2026-04-14). Model A: CC processing fees are absorbed by the
# company and are NOT deducted from the owner's net payout.
# Owner net = gross_revenue - commission. Period.


@dataclass
class OwnerPayoutLineItem:
    name: str
    amount: Decimal
    category: str  # "commissionable", "pass_through", "deduction"


@dataclass
class OwnerPayoutBreakdown:
    gross_revenue: Decimal = Decimal("0.00")
    pass_through_total: Decimal = Decimal("0.00")
    commission_rate: Decimal = Decimal("0.00")
    commission_amount: Decimal = Decimal("0.00")
    cc_processing_fee: Decimal = Decimal("0.00")
    net_owner_payout: Decimal = Decimal("0.00")
    total_collected: Decimal = Decimal("0.00")
    details: list[OwnerPayoutLineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gross_revenue": float(self.gross_revenue),
            "pass_through_total": float(self.pass_through_total),
            "commission_rate": float(self.commission_rate),
            "commission_amount": float(self.commission_amount),
            "cc_processing_fee": float(self.cc_processing_fee),
            "net_owner_payout": float(self.net_owner_payout),
            "total_collected": float(self.total_collected),
            "details": [
                {"name": d.name, "amount": float(d.amount), "category": d.category}
                for d in self.details
            ],
        }


def _is_pass_through(item: BucketedItem) -> bool:
    """Determine whether a line item is pass-through (excluded from commission base)."""
    if item.item_type in PASS_THROUGH_TYPES:
        return True
    if item.bucket in PASS_THROUGH_BUCKETS:
        return True
    bucket = classify_item(item.item_type, item.name)
    if bucket in PASS_THROUGH_BUCKETS:
        return True
    name_lower = item.name.strip().lower()
    if "clean" in name_lower:
        return True
    return False


def calculate_owner_payout(
    items: Sequence[BucketedItem],
    commission_rate: Decimal,
) -> OwnerPayoutBreakdown:
    """Compute the owner's net payout from a set of invoice line items.

    Model A (confirmed 2026-04-14): CC processing fees are absorbed by the
    company and are NOT deducted from the owner's share.

    Commissionable items:   Rent, Pet Fees, Extra Guest Fees, Add-Ons
    Pass-through items:     Cleaning Fees, ADW, Processing Fee, Taxes, Deposits

    Formula:
        gross_revenue    = sum of commissionable items
        commission       = gross_revenue × commission_rate / 100
        net_owner_payout = gross_revenue - commission
    """
    breakdown = OwnerPayoutBreakdown(commission_rate=commission_rate)
    total_collected = Decimal("0.00")

    for item in items:
        total_collected += item.amount
        if _is_pass_through(item):
            breakdown.pass_through_total += item.amount
            breakdown.details.append(OwnerPayoutLineItem(
                name=item.name, amount=item.amount, category="pass_through",
            ))
        else:
            breakdown.gross_revenue += item.amount
            breakdown.details.append(OwnerPayoutLineItem(
                name=item.name, amount=item.amount, category="commissionable",
            ))

    breakdown.total_collected = _money(total_collected)
    breakdown.gross_revenue = _money(breakdown.gross_revenue)
    breakdown.pass_through_total = _money(breakdown.pass_through_total)

    breakdown.commission_amount = _money(
        breakdown.gross_revenue * commission_rate / ONE_HUNDRED
    )

    # CC processing fee is zero — absorbed by the company (Model A).
    breakdown.cc_processing_fee = Decimal("0.00")

    breakdown.net_owner_payout = _money(
        breakdown.gross_revenue
        - breakdown.commission_amount
    )

    breakdown.details.append(OwnerPayoutLineItem(
        name=f"Management Commission ({commission_rate}%)",
        amount=-breakdown.commission_amount,
        category="deduction",
    ))

    return breakdown


# ---------------------------------------------------------------------------
# Predictive Analytics — 30/60/90-day revenue & tax projections
# ---------------------------------------------------------------------------

@dataclass
class ProjectionWindow:
    label: str
    days: int
    start: date
    end: date
    confirmed_revenue: Decimal = Decimal("0.00")
    projected_revenue: Decimal = Decimal("0.00")
    cancellation_adjusted: Decimal = Decimal("0.00")
    estimated_owner_payout: Decimal = Decimal("0.00")
    estimated_tax_obligation: Decimal = Decimal("0.00")
    reservation_count: int = 0
    cancelled_count: int = 0

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "days": self.days,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "confirmed_revenue": float(self.confirmed_revenue),
            "projected_revenue": float(self.projected_revenue),
            "cancellation_adjusted": float(self.cancellation_adjusted),
            "estimated_owner_payout": float(self.estimated_owner_payout),
            "estimated_tax_obligation": float(self.estimated_tax_obligation),
            "reservation_count": self.reservation_count,
            "cancellation_rate_applied": float(self._cancel_rate),
        }

    @property
    def _cancel_rate(self) -> Decimal:
        total = self.reservation_count + self.cancelled_count
        if total == 0:
            return Decimal("0.00")
        return _money(Decimal(str(self.cancelled_count)) / Decimal(str(total)) * ONE_HUNDRED)


OWNER_PAYOUT_RATIO = Decimal("0.75")
WINDOWS = [("30-day", 30), ("60-day", 60), ("90-day", 90)]


class PredictiveAnalytics:
    """Project owner payouts and tax obligations for upcoming windows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def project(self, reference_date: date | None = None) -> list[dict]:
        from backend.models.reservation import Reservation
        from backend.models.property import Property

        today = reference_date or date.today()
        historical_cancel_rate = await self._historical_cancellation_rate(Reservation, today)
        results = []

        for label, days in WINDOWS:
            window_start = today
            window_end = today + timedelta(days=days)

            window = ProjectionWindow(
                label=label, days=days, start=window_start, end=window_end,
            )

            confirmed_stmt = (
                select(
                    func.count(Reservation.id),
                    func.coalesce(func.sum(Reservation.total_amount), 0),
                )
                .where(and_(
                    Reservation.check_in_date >= window_start,
                    Reservation.check_in_date < window_end,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                ))
            )
            row = (await self.db.execute(confirmed_stmt)).one()
            window.reservation_count = int(row[0])
            window.confirmed_revenue = _money(Decimal(str(row[1])))

            cancelled_stmt = (
                select(func.count(Reservation.id))
                .where(and_(
                    Reservation.check_in_date >= today - timedelta(days=180),
                    Reservation.check_in_date < today,
                    Reservation.status == "cancelled",
                ))
            )
            window.cancelled_count = (await self.db.execute(cancelled_stmt)).scalar() or 0

            keep_rate = (ONE_HUNDRED - historical_cancel_rate) / ONE_HUNDRED
            window.cancellation_adjusted = _money(window.confirmed_revenue * keep_rate)
            window.projected_revenue = window.cancellation_adjusted

            window.estimated_owner_payout = _money(
                window.cancellation_adjusted * OWNER_PAYOUT_RATIO
            )

            avg_tax_rate = await self._avg_effective_tax_rate(Reservation, today)
            window.estimated_tax_obligation = _money(
                window.cancellation_adjusted * avg_tax_rate / ONE_HUNDRED
            )

            results.append(window.to_dict())

        predict_logger.info(
            "predictive_projection_complete",
            windows=len(results),
            cancel_rate=float(historical_cancel_rate),
        )
        return results

    async def _historical_cancellation_rate(self, Reservation: Any, today: date) -> Decimal:
        lookback = today - timedelta(days=365)
        stmt = select(
            func.count(Reservation.id).filter(Reservation.status == "cancelled"),
            func.count(Reservation.id),
        ).where(and_(
            Reservation.check_in_date >= lookback,
            Reservation.check_in_date < today,
        ))
        row = (await self.db.execute(stmt)).one()
        total = int(row[1])
        if total == 0:
            return Decimal("8.00")  # industry default 8%
        cancelled = int(row[0])
        return _money(Decimal(str(cancelled)) / Decimal(str(total)) * ONE_HUNDRED)

    async def _avg_effective_tax_rate(self, Reservation: Any, today: date) -> Decimal:
        """Compute the average effective tax rate from recent completed reservations."""
        lookback = today - timedelta(days=180)
        stmt = (
            select(Reservation.total_amount, Reservation.tax_amount)
            .where(and_(
                Reservation.check_out_date >= lookback,
                Reservation.check_out_date < today,
                Reservation.status.in_(["confirmed", "checked_out", "completed"]),
                Reservation.total_amount > 0,
                Reservation.tax_amount > 0,
            ))
            .limit(200)
        )
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return Decimal("18.00")  # safe fallback
        total_rev = sum(Decimal(str(r[0] or 0)) for r in rows)
        total_tax = sum(Decimal(str(r[1] or 0)) for r in rows)
        if total_rev == Decimal("0"):
            return Decimal("18.00")
        return _money(total_tax / total_rev * ONE_HUNDRED)
