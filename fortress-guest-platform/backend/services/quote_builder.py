"""
Quote Builder — Multi-property pricing engine for the Lead Quoting System.

Calculates itemized price breakdowns (base_rent, taxes, fees, total) for
any property and date range. Uses the synced Streamline rate_card JSONB
when populated; falls back to the proven DirectBookingEngine bedroom-based
rates when rate_card is NULL.

Rule 7 compliance: All math happens server-side with DECIMAL precision.
The AI never guesses pricing.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.property import Property

logger = structlog.get_logger()

TWO_PLACES = Decimal("0.01")

# Fannin County GA tax: state 4% + county 4% + local lodging 5% = 13%
DEFAULT_TAX_RATE = Decimal("0.13")

BEDROOM_BASE_RATES: Dict[int, Decimal] = {
    1: Decimal("149.00"),
    2: Decimal("199.00"),
    3: Decimal("269.00"),
    4: Decimal("329.00"),
    5: Decimal("399.00"),
    6: Decimal("449.00"),
    7: Decimal("549.00"),
    8: Decimal("649.00"),
}
_DEFAULT_RATE = Decimal("299.00")

CLEANING_FEES: Dict[str, Decimal] = {
    "1-2": Decimal("150.00"),
    "3-4": Decimal("250.00"),
    "5-6": Decimal("350.00"),
    "7+":  Decimal("450.00"),
}


def _cleaning_fee_for_bedrooms(bedrooms: int) -> Decimal:
    if bedrooms <= 2:
        return CLEANING_FEES["1-2"]
    elif bedrooms <= 4:
        return CLEANING_FEES["3-4"]
    elif bedrooms <= 6:
        return CLEANING_FEES["5-6"]
    return CLEANING_FEES["7+"]


def _weekend_seasonal_rate(base: Decimal, d: date) -> Decimal:
    """Apply weekend (+20%) and peak season (+15%) premiums."""
    rate = base
    if d.weekday() in (4, 5):
        rate = (rate * Decimal("1.20")).quantize(TWO_PLACES, ROUND_HALF_UP)
    if d.month in (6, 7, 8, 10, 12):
        rate = (rate * Decimal("1.15")).quantize(TWO_PLACES, ROUND_HALF_UP)
    return rate


def _parse_streamline_date(ds: Optional[str]) -> Optional[date]:
    """Parse MM/DD/YYYY date strings from Streamline rate_card."""
    if not ds:
        return None
    try:
        parts = ds.split("/")
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _nightly_from_rate_card(rate_card: Dict, stay_date: date) -> Optional[Decimal]:
    """Find the applicable nightly rate from rate_card for a given date."""
    for entry in rate_card.get("rates", []):
        start = _parse_streamline_date(entry.get("start_date"))
        end = _parse_streamline_date(entry.get("end_date"))
        if start and end and start <= stay_date <= end:
            nightly = entry.get("nightly")
            if nightly is not None:
                return Decimal(str(nightly)).quantize(TWO_PLACES, ROUND_HALF_UP)
    return None


def _fees_from_rate_card(rate_card: Dict) -> Decimal:
    """Sum all fixed fees from rate_card (cleaning, processing, etc.)."""
    total = Decimal("0")
    for fee in rate_card.get("fees", []):
        amount = fee.get("amount")
        if amount is not None:
            total += Decimal(str(amount)).quantize(TWO_PLACES, ROUND_HALF_UP)
    return total


def _tax_rate_from_rate_card(rate_card: Dict) -> Decimal:
    """Sum percentage-type tax rates from rate_card."""
    total = Decimal("0")
    for tax in rate_card.get("taxes", []):
        rate = tax.get("rate")
        ttype = (tax.get("type") or "").lower()
        if rate is not None and "percent" in ttype:
            total += Decimal(str(rate))
    return total if total > 0 else DEFAULT_TAX_RATE


async def calculate_property_quote(
    property_id: UUID,
    check_in: date,
    check_out: date,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Calculate an itemized price breakdown for a property and date range.

    Returns a dict with: property_id, property_name, nights, base_rent,
    fees, taxes, total_price, pricing_source, nightly_breakdown.

    Pricing source priority:
      1. Streamline rate_card JSONB (if populated with rates, fees, taxes)
      2. DirectBookingEngine bedroom-based fallback (proven production rates)
    """
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise ValueError(f"Property {property_id} not found")

    nights = (check_out - check_in).days
    if nights < 1:
        raise ValueError("check_out must be after check_in")

    rate_card = prop.rate_card
    use_rate_card = (
        rate_card is not None
        and isinstance(rate_card, dict)
        and len(rate_card.get("rates", [])) > 0
    )

    nightly_breakdown = []
    base_rent = Decimal("0")

    if use_rate_card:
        pricing_source = "streamline_rate_card"
        bedroom_base = BEDROOM_BASE_RATES.get(prop.bedrooms, _DEFAULT_RATE)

        current = check_in
        while current < check_out:
            rate = _nightly_from_rate_card(rate_card, current)
            if rate is None:
                rate = _weekend_seasonal_rate(bedroom_base, current)
            nightly_breakdown.append({"date": current.isoformat(), "rate": str(rate)})
            base_rent += rate
            current += timedelta(days=1)

        fees = _fees_from_rate_card(rate_card)
        tax_rate = _tax_rate_from_rate_card(rate_card)
    else:
        pricing_source = "bedroom_rate_fallback"
        bedroom_base = BEDROOM_BASE_RATES.get(prop.bedrooms, _DEFAULT_RATE)

        current = check_in
        while current < check_out:
            rate = _weekend_seasonal_rate(bedroom_base, current)
            nightly_breakdown.append({"date": current.isoformat(), "rate": str(rate)})
            base_rent += rate
            current += timedelta(days=1)

        fees = _cleaning_fee_for_bedrooms(prop.bedrooms)
        tax_rate = DEFAULT_TAX_RATE

    taxable_amount = base_rent + fees
    taxes = (taxable_amount * tax_rate).quantize(TWO_PLACES, ROUND_HALF_UP)
    total_price = base_rent + fees + taxes

    logger.info(
        "quote_calculated",
        property=prop.name,
        nights=nights,
        base_rent=str(base_rent),
        fees=str(fees),
        taxes=str(taxes),
        total=str(total_price),
        source=pricing_source,
    )

    return {
        "property_id": str(prop.id),
        "property_name": prop.name,
        "bedrooms": prop.bedrooms,
        "nights": nights,
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "base_rent": str(base_rent),
        "fees": str(fees),
        "tax_rate": str(tax_rate),
        "taxes": str(taxes),
        "total_price": str(total_price),
        "pricing_source": pricing_source,
        "nightly_breakdown": nightly_breakdown,
    }
