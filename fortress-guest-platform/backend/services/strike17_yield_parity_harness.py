"""
Strike 17 cutover audit — sovereign rent vs Streamline-shaped ``rate_card``.

Uses the same ledger path as checkout (``build_local_rent_quote``). For a full
Streamline deterministic total (fees/taxes/ancillaries), call the VRS quote API
separately and compare out-of-band.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.quote_builder import build_local_rent_quote


async def sovereign_rent_snapshot_from_ledger(
    db: AsyncSession,
    *,
    property_id: UUID,
    check_in: date,
    check_out: date,
) -> dict[str, Any]:
    """
    Deterministic rent snapshot from ``properties.rate_card`` (synced from Streamline).

    Raises :class:`QuoteBuilderError` when min-stay or nightly coverage fails.
    """
    quote = await build_local_rent_quote(property_id, check_in, check_out, db)
    return {
        "property_id": str(quote.property_id),
        "property_name": quote.property_name,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "nights": quote.nights,
        "rent": format(quote.rent, ".2f"),
        "rent_decimal": quote.rent,
        "pricing_source": quote.pricing_source,
        "nightly_breakdown": [
            {"date": d.isoformat(), "rate": format(r, ".2f")} for d, r in quote.nightly_breakdown
        ],
    }


def rent_totals_close(
    *,
    sovereign_rent: Decimal | str,
    streamline_rent: Decimal | str,
    max_delta: Decimal = Decimal("0.02"),
) -> bool:
    """Ad-hoc comparison helper for audit scripts (currency, two decimal places)."""
    a = Decimal(str(sovereign_rent)).quantize(Decimal("0.01"))
    b = Decimal(str(streamline_rent)).quantize(Decimal("0.01"))
    return abs(a - b) <= max_delta
