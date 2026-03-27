"""
Quote Builder — local ledger pricing only.

Pricing is sourced exclusively from the local Postgres `properties.rate_card`
ledger. If required nightly rates, cleaning fees, or taxes are missing, the
calculation fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.property import Property

logger = structlog.get_logger()

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class LocalLedgerQuote:
    property_id: UUID
    property_name: str
    nights: int
    rent: Decimal
    cleaning: Decimal
    admin_fee: Decimal
    taxes: Decimal
    total: Decimal
    tax_rate: Decimal
    nightly_breakdown: tuple[tuple[date, Decimal], ...]
    pricing_source: str = "local_ledger"


@dataclass(frozen=True)
class LocalLedgerRentQuote:
    property_id: UUID
    property_name: str
    nights: int
    rent: Decimal
    nightly_breakdown: tuple[tuple[date, Decimal], ...]
    pricing_source: str = "local_ledger"


class QuoteBuilderError(ValueError):
    """Raised when the local pricing ledger is incomplete or invalid."""


def _parse_streamline_date(ds: str | None) -> date | None:
    """Parse MM/DD/YYYY or ISO YYYY-MM-DD date strings from Streamline rate_card."""
    if not ds:
        return None
    try:
        normalized = ds.strip()
        if "-" in normalized:
            return date.fromisoformat(normalized)
        parts = normalized.split("/")
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _to_money(value: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, ROUND_HALF_UP)
    except Exception as exc:
        raise QuoteBuilderError(f"Invalid money value for {field_name}") from exc


def _require_rate_card(rate_card: Any) -> dict[str, Any]:
    if not isinstance(rate_card, dict):
        raise QuoteBuilderError("Property pricing ledger is missing")
    if not rate_card.get("rates"):
        raise QuoteBuilderError("Property nightly ledger is missing")
    return rate_card


def _min_nights_from_rate_entry(entry: dict[str, Any]) -> int:
    """Minimum stay required for the rate row; default 1 when Streamline omits it."""
    raw = entry.get("min_nights")
    if raw is None:
        raw = entry.get("minimum_days")
    if raw is None or raw == "":
        return 1
    try:
        n = int(Decimal(str(raw)))
    except Exception:
        return 1
    return max(1, n)


def _nightly_from_rate_card(rate_card: dict[str, Any], stay_date: date) -> Decimal | None:
    """Find the applicable nightly rate from rate_card for a given date."""
    pair = _nightly_and_min_nights_from_rate_card(rate_card, stay_date)
    return pair[0] if pair else None


def _nightly_and_min_nights_from_rate_card(
    rate_card: dict[str, Any],
    stay_date: date,
) -> tuple[Decimal, int] | None:
    """Nightly rent and Streamline min-stay for the matching rate row (yield rules)."""
    for entry in rate_card.get("rates", []):
        start = _parse_streamline_date(entry.get("start_date"))
        end = _parse_streamline_date(entry.get("end_date"))
        if start and end and start <= stay_date <= end:
            nightly = entry.get("nightly")
            if nightly is None:
                return None
            money = _to_money(nightly, field_name=f"nightly rate for {stay_date.isoformat()}")
            return (money, _min_nights_from_rate_entry(entry))
    return None


def _fee_label(fee: dict[str, Any]) -> str:
    return " ".join(
        str(part).strip().lower()
        for part in (
            fee.get("name"),
            fee.get("code"),
            fee.get("type"),
            fee.get("category"),
        )
        if part
    )


def _rate_card_cleaning_and_admin_fees(rate_card: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """
    Extract cleaning and admin-style fees from the local rate_card JSON.

    Cleaning: name/code/type/category contains ``clean``.
    Admin: contains ``admin``, ``administration``, or ``management``.
    Any other non-zero fee fails closed (prevents silent omission of charges).
    """
    cleaning = Decimal("0.00")
    admin = Decimal("0.00")
    for fee in rate_card.get("fees", []):
        amount = fee.get("amount")
        if amount is None:
            continue

        normalized_name = _fee_label(fee)
        normalized_amount = _to_money(amount, field_name="fee amount")
        if normalized_amount == Decimal("0.00"):
            continue
        if "clean" in normalized_name:
            cleaning += normalized_amount
            continue
        if any(
            token in normalized_name
            for token in ("admin", "administration", "management")
        ):
            admin += normalized_amount
            continue
        raise QuoteBuilderError(
            "Unsupported fee in local rate_card (not cleaning/admin): "
            f"{fee.get('name') or fee.get('type') or 'unknown'}"
        )
    return cleaning, admin


def _tax_rate_from_rate_card(rate_card: dict[str, Any]) -> Decimal:
    """Sum percentage-type tax rates from the local ledger."""
    total = Decimal("0.00")
    for tax in rate_card.get("taxes", []):
        rate = tax.get("rate")
        ttype = (tax.get("type") or "").lower()
        if rate is not None and "percent" in ttype:
            total += Decimal(str(rate))
    if total <= Decimal("0.00"):
        raise QuoteBuilderError("Property tax ledger is missing")
    return total


async def build_local_ledger_quote(
    property_id: UUID,
    check_in: date,
    check_out: date,
    db: AsyncSession,
) -> LocalLedgerQuote:
    """Calculate a deterministic booking quote from the local pricing ledger."""
    rent_quote = await build_local_rent_quote(property_id, check_in, check_out, db)
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise QuoteBuilderError(f"Property {property_id} not found")

    rate_card = _require_rate_card(prop.rate_card)
    cleaning, admin_fee = _rate_card_cleaning_and_admin_fees(rate_card)
    tax_rate = _tax_rate_from_rate_card(rate_card)
    taxable = rent_quote.rent + cleaning + admin_fee
    taxes = (taxable * tax_rate).quantize(TWO_PLACES, ROUND_HALF_UP)
    total = (taxable + taxes).quantize(TWO_PLACES, ROUND_HALF_UP)

    logger.info(
        "quote_calculated",
        property=prop.name,
        nights=rent_quote.nights,
        rent=str(rent_quote.rent),
        cleaning=str(cleaning),
        admin_fee=str(admin_fee),
        taxes=str(taxes),
        total=str(total),
        source="local_ledger",
    )

    return LocalLedgerQuote(
        property_id=prop.id,
        property_name=prop.name,
        nights=rent_quote.nights,
        rent=rent_quote.rent.quantize(TWO_PLACES, ROUND_HALF_UP),
        cleaning=cleaning.quantize(TWO_PLACES, ROUND_HALF_UP),
        admin_fee=admin_fee.quantize(TWO_PLACES, ROUND_HALF_UP),
        taxes=taxes,
        total=total,
        tax_rate=tax_rate,
        nightly_breakdown=rent_quote.nightly_breakdown,
    )


async def build_local_rent_quote(
    property_id: UUID,
    check_in: date,
    check_out: date,
    db: AsyncSession,
) -> LocalLedgerRentQuote:
    """Calculate deterministic nightly rent without tax/fee dependencies."""
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise QuoteBuilderError(f"Property {property_id} not found")

    nights = (check_out - check_in).days
    if nights < 1:
        raise QuoteBuilderError("check_out must be after check_in")

    rate_card = _require_rate_card(prop.rate_card)
    nightly_breakdown: list[tuple[date, Decimal]] = []
    rent = Decimal("0.00")
    required_min_nights = 1
    current = check_in
    while current < check_out:
        pair = _nightly_and_min_nights_from_rate_card(rate_card, current)
        if pair is None:
            raise QuoteBuilderError(
                f"Property nightly ledger is incomplete for {current.isoformat()}"
            )
        nightly_rate, row_min = pair
        required_min_nights = max(required_min_nights, row_min)
        nightly_breakdown.append((current, nightly_rate))
        rent += nightly_rate
        current += timedelta(days=1)

    if nights < required_min_nights:
        raise QuoteBuilderError(
            f"Stay length {nights} night(s) is below minimum stay {required_min_nights} "
            "for the selected dates (Streamline yield rule)."
        )

    return LocalLedgerRentQuote(
        property_id=prop.id,
        property_name=prop.name,
        nights=nights,
        rent=rent.quantize(TWO_PLACES, ROUND_HALF_UP),
        nightly_breakdown=tuple(nightly_breakdown),
    )


async def calculate_property_quote(
    property_id: UUID,
    check_in: date,
    check_out: date,
    db: AsyncSession,
    *,
    require_local_ledger: bool = False,
) -> dict[str, Any]:
    """
    Calculate an itemized price breakdown for a property and date range.

    Returns a dict with: property_id, property_name, nights, base_rent,
    fees, taxes, total_price, pricing_source, nightly_breakdown.

    This function now prices exclusively from the local Postgres ledger.
    `require_local_ledger` remains for call-site compatibility and is enforced.
    """
    del require_local_ledger

    quote = await build_local_ledger_quote(property_id, check_in, check_out, db)

    fee_total = (quote.cleaning + quote.admin_fee).quantize(TWO_PLACES, ROUND_HALF_UP)
    return {
        "property_id": str(quote.property_id),
        "property_name": quote.property_name,
        "nights": quote.nights,
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "base_rent": str(quote.rent),
        "cleaning": str(quote.cleaning),
        "admin_fee": str(quote.admin_fee),
        "fees": str(fee_total),
        "tax_rate": str(quote.tax_rate),
        "taxes": str(quote.taxes),
        "total_price": str(quote.total),
        "pricing_source": quote.pricing_source,
        "nightly_breakdown": [
            {"date": stay_date.isoformat(), "rate": str(rate)}
            for stay_date, rate in quote.nightly_breakdown
        ],
    }
