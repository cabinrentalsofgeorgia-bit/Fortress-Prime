"""Sovereign Fast Quote pricing service."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.financial_primitives import Fee, PropertyFee, PropertyTax, Tax
from backend.models.pricing import QuoteLineItem, QuoteRequest, QuoteResponse
from backend.models.pricing_override import PricingOverride
from backend.models.property import Property
from backend.services.quote_builder import QuoteBuilderError, build_local_rent_quote
from backend.services.sovereign_yield_authority import SovereignYieldAuthority


TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100.00")


class PricingError(ValueError):
    """Raised when a quote request cannot be satisfied."""


def _to_money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


async def _load_overlapping_pricing_overrides(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
) -> list[PricingOverride]:
    stmt = (
        select(PricingOverride)
        .where(PricingOverride.property_id == property_id)
        .where(PricingOverride.start_date < check_out)
        .where(PricingOverride.end_date >= check_in)
        .order_by(PricingOverride.start_date.asc(), PricingOverride.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_applicable_taxes(
    db: AsyncSession,
    property_id: UUID,
) -> list[Tax]:
    stmt = (
        select(Tax)
        .join(PropertyTax, PropertyTax.tax_id == Tax.id)
        .where(PropertyTax.property_id == property_id)
        .where(PropertyTax.is_active.is_(True))
        .where(Tax.is_active.is_(True))
        .order_by(Tax.name.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_applicable_fees(
    db: AsyncSession,
    property_id: UUID,
) -> list[Fee]:
    stmt = (
        select(Fee)
        .join(PropertyFee, PropertyFee.fee_id == Fee.id)
        .where(PropertyFee.property_id == property_id)
        .where(PropertyFee.is_active.is_(True))
        .where(Fee.is_active.is_(True))
        .order_by(Fee.name.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _matching_override_for_night(
    stay_date: date,
    overrides: Iterable[PricingOverride],
) -> PricingOverride | None:
    match: PricingOverride | None = None
    for override in overrides:
        if override.start_date <= stay_date <= override.end_date:
            if match is not None and match.id != override.id:
                raise PricingError(
                    f"Conflicting pricing overrides found for {stay_date.isoformat()}"
                )
            match = override
    return match


def _build_override_line_items(
    nightly_breakdown: Iterable[tuple[date, Decimal]],
    overrides: list[PricingOverride],
) -> tuple[list[QuoteLineItem], Decimal]:
    applied_amounts: "OrderedDict[str, tuple[PricingOverride, Decimal]]" = OrderedDict()
    total_adjustment = Decimal("0.00")

    for stay_date, nightly_rate in nightly_breakdown:
        override = _matching_override_for_night(stay_date, overrides)
        if override is None:
            continue
        adjustment_ratio = Decimal(str(override.adjustment_percentage)) / ONE_HUNDRED
        nightly_adjustment = _to_money(nightly_rate * adjustment_ratio)
        current_override, current_amount = applied_amounts.get(
            str(override.id),
            (override, Decimal("0.00")),
        )
        applied_amounts[str(override.id)] = (
            current_override,
            current_amount + nightly_adjustment,
        )
        total_adjustment += nightly_adjustment

    line_items: list[QuoteLineItem] = []
    for override, amount in applied_amounts.values():
        rounded_amount = _to_money(amount)
        adjustment_percentage = _to_money(Decimal(str(override.adjustment_percentage)))
        if rounded_amount == Decimal("0.00"):
            continue
        line_items.append(
            QuoteLineItem(
                description=(
                    "Yield Adjustment Discount "
                    f"({adjustment_percentage}% {override.start_date.isoformat()} to {override.end_date.isoformat()})"
                    if rounded_amount < 0
                    else "Yield Adjustment Premium "
                    f"(+{adjustment_percentage}% {override.start_date.isoformat()} to {override.end_date.isoformat()})"
                ),
                amount=rounded_amount,
                type="discount" if rounded_amount < 0 else "fee",
            )
        )

    return line_items, _to_money(total_adjustment)


def _build_fee_line_items(
    *,
    pets: int,
    fees: list[Fee],
) -> tuple[list[QuoteLineItem], Decimal]:
    standard_fees = [fee for fee in fees if not bool(fee.is_pet_fee)]
    if not standard_fees:
        raise PricingError("Property fee ledger is missing")

    line_items: list[QuoteLineItem] = []
    total_fees = Decimal("0.00")
    for fee in fees:
        if bool(fee.is_pet_fee) and pets < 1:
            continue
        amount = _to_money(Decimal(str(fee.flat_amount)))
        if amount == Decimal("0.00"):
            continue
        total_fees += amount
        line_items.append(
            QuoteLineItem(
                description=fee.name,
                amount=amount,
                type="fee",
            )
        )
    return line_items, _to_money(total_fees)


def _build_tax_line_items(
    *,
    tax_base: Decimal,
    taxes: list[Tax],
) -> tuple[list[QuoteLineItem], Decimal]:
    if not taxes:
        raise PricingError("Property tax ledger is missing")

    line_items: list[QuoteLineItem] = []
    total_taxes = Decimal("0.00")
    for tax in taxes:
        rate = Decimal(str(tax.percentage_rate))
        tax_amount = _to_money(tax_base * (rate / ONE_HUNDRED))
        if tax_amount == Decimal("0.00"):
            continue
        total_taxes += tax_amount
        line_items.append(
            QuoteLineItem(
                description=tax.name,
                amount=tax_amount,
                type="tax",
            )
        )
    return line_items, _to_money(total_taxes)


async def calculate_fast_quote(
    request: QuoteRequest,
    db: AsyncSession,
) -> QuoteResponse:
    nights = (request.check_out - request.check_in).days
    if nights < 1:
        raise PricingError("check_out must be after check_in")

    property_record = await db.get(Property, request.property_id)
    if property_record is None or not property_record.is_active:
        raise PricingError("Property not found")

    yield_violations = await SovereignYieldAuthority.validate_stay_constraints(
        db,
        request.property_id,
        request.check_in,
        request.check_out,
    )
    if yield_violations:
        raise PricingError("; ".join(yield_violations))

    total_guests = request.adults + request.children
    is_bookable = total_guests <= int(property_record.max_guests or 0)
    try:
        rent_quote = await build_local_rent_quote(
            request.property_id,
            request.check_in,
            request.check_out,
            db,
        )
    except QuoteBuilderError as exc:
        raise PricingError(str(exc)) from exc

    fees = await _load_applicable_fees(db, request.property_id)
    taxes = await _load_applicable_taxes(db, request.property_id)
    overrides = await _load_overlapping_pricing_overrides(
        db,
        request.property_id,
        request.check_in,
        request.check_out,
    )
    override_line_items, total_adjustment = _build_override_line_items(
        rent_quote.nightly_breakdown,
        overrides,
    )
    fee_line_items, total_fees = _build_fee_line_items(
        pets=request.pets,
        fees=fees,
    )
    adjusted_rent = _to_money(rent_quote.rent + total_adjustment)
    tax_line_items, total_tax_amount = _build_tax_line_items(
        tax_base=_to_money(adjusted_rent + total_fees),
        taxes=taxes,
    )
    total_amount = _to_money(adjusted_rent + total_fees + total_tax_amount)

    nightly_rate = (rent_quote.rent / Decimal(nights)).quantize(TWO_PLACES) if nights else Decimal("0.00")
    line_items = [
        QuoteLineItem(
            description=f"{nights} night stay @ ${nightly_rate} / night",
            amount=rent_quote.rent,
            type="rent",
        ),
        *override_line_items,
        *fee_line_items,
        *tax_line_items,
    ]

    return QuoteResponse(
        property_id=property_record.id,
        currency="USD",
        line_items=line_items,
        total_amount=total_amount,
        is_bookable=is_bookable,
    )
