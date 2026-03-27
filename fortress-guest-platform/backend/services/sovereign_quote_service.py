"""
Unified sovereign quote: SQL fee/tax ledgers when linked, else ``rate_card`` ledger.

This is the single itemization path for fast quote, signed quotes, and hold snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.financial_primitives import PropertyFee, PropertyTax
from backend.models.pricing import QuoteLineItem, QuoteRequest
from backend.models.property import Property
from backend.services.pricing_service import PricingError, calculate_fast_quote
from backend.services.quote_builder import (
    QuoteBuilderError,
    build_local_ledger_quote,
)
from backend.services.sovereign_yield_authority import SovereignYieldAuthority

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class SovereignQuoteBreakdown:
    property_id: UUID
    property_name: str
    pricing_source: str
    rent: Decimal
    cleaning: Decimal
    admin_fee: Decimal
    pet_fee: Decimal
    taxes: Decimal
    total: Decimal
    line_items: tuple[dict[str, str], ...]


async def _property_has_sql_fee_and_tax_ledgers(
    db: AsyncSession,
    property_id: UUID,
) -> bool:
    fee_count = await db.scalar(
        select(func.count())
        .select_from(PropertyFee)
        .where(
            PropertyFee.property_id == property_id,
            PropertyFee.is_active.is_(True),
        )
    )
    tax_count = await db.scalar(
        select(func.count())
        .select_from(PropertyTax)
        .where(
            PropertyTax.property_id == property_id,
            PropertyTax.is_active.is_(True),
        )
    )
    return int(fee_count or 0) > 0 and int(tax_count or 0) > 0


def _rollup_from_sql_line_items(
    line_items: list[QuoteLineItem],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Derive rent, cleaning, admin, pet, taxes from calculator line items."""
    rent = Decimal("0.00")
    cleaning = Decimal("0.00")
    admin = Decimal("0.00")
    pet = Decimal("0.00")
    taxes = Decimal("0.00")
    for li in line_items:
        if li.type == "rent":
            rent += li.amount
        elif li.type == "tax":
            taxes += li.amount
        elif li.type == "discount":
            rent += li.amount
        elif li.type == "fee":
            desc = li.description.lower()
            if "pet" in desc:
                pet += li.amount
            elif "clean" in desc:
                cleaning += li.amount
            elif "admin" in desc or "management" in desc or "administration" in desc:
                admin += li.amount
            else:
                admin += li.amount
    return (
        rent.quantize(TWO_PLACES, ROUND_HALF_UP),
        cleaning.quantize(TWO_PLACES, ROUND_HALF_UP),
        admin.quantize(TWO_PLACES, ROUND_HALF_UP),
        pet.quantize(TWO_PLACES, ROUND_HALF_UP),
        taxes.quantize(TWO_PLACES, ROUND_HALF_UP),
    )


def _line_items_to_payload(line_items: list[QuoteLineItem]) -> tuple[dict[str, str], ...]:
    out: list[dict[str, str]] = []
    for li in line_items:
        out.append(
            {
                "type": li.type,
                "description": li.description,
                "amount": str(li.amount.quantize(TWO_PLACES, ROUND_HALF_UP)),
            }
        )
    return tuple(out)


async def compute_sovereign_quote(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    *,
    adults: int,
    children: int,
    pets: int,
) -> SovereignQuoteBreakdown:
    prop = await db.get(Property, property_id)
    if prop is None or not prop.is_active:
        raise QuoteBuilderError("Property not found")

    if await _property_has_sql_fee_and_tax_ledgers(db, property_id):
        request = QuoteRequest(
            property_id=property_id,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            pets=pets,
        )
        try:
            response = await calculate_fast_quote(request, db)
        except PricingError as exc:
            raise QuoteBuilderError(str(exc)) from exc

        rent, cleaning, admin_fee, pet_fee, taxes = _rollup_from_sql_line_items(
            response.line_items
        )
        total = response.total_amount.quantize(TWO_PLACES, ROUND_HALF_UP)
        return SovereignQuoteBreakdown(
            property_id=prop.id,
            property_name=prop.name,
            pricing_source="sql_ledger",
            rent=rent,
            cleaning=cleaning,
            admin_fee=admin_fee,
            pet_fee=pet_fee,
            taxes=taxes,
            total=total,
            line_items=_line_items_to_payload(response.line_items),
        )

    ledger_yield = await SovereignYieldAuthority.validate_stay_constraints(
        db, property_id, check_in, check_out
    )
    if ledger_yield:
        raise QuoteBuilderError("; ".join(ledger_yield))

    quote = await build_local_ledger_quote(property_id, check_in, check_out, db)
    items: list[dict[str, str]] = [
        {
            "type": "rent",
            "description": f"{quote.nights} night stay",
            "amount": str(quote.rent),
        },
    ]
    if quote.cleaning > Decimal("0.00"):
        items.append(
            {
                "type": "fee",
                "description": "Cleaning fee",
                "amount": str(quote.cleaning),
            }
        )
    if quote.admin_fee > Decimal("0.00"):
        items.append(
            {
                "type": "fee",
                "description": "Admin fee",
                "amount": str(quote.admin_fee),
            }
        )
    items.append(
        {
            "type": "tax",
            "description": "Taxes (local rate_card)",
            "amount": str(quote.taxes),
        }
    )
    return SovereignQuoteBreakdown(
        property_id=quote.property_id,
        property_name=quote.property_name,
        pricing_source=quote.pricing_source,
        rent=quote.rent,
        cleaning=quote.cleaning,
        admin_fee=quote.admin_fee,
        pet_fee=Decimal("0.00"),
        taxes=quote.taxes,
        total=quote.total,
        line_items=tuple(items),
    )


def total_from_line_items(line_items: Iterable[dict[str, str]]) -> Decimal:
    """Sum decimal amounts from serialized line items."""
    total = Decimal("0.00")
    for row in line_items:
        total += Decimal(str(row["amount"]))
    return total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
