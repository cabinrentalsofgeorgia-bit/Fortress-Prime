"""
Unified Cancellation Refund Engine — integer-cents, ledger-aware.

Replaces the blunt percentage-based refund logic in both
``reservation_engine.py`` and ``direct_booking.py`` with a single
function that reads the Universal Ledger ``LedgerLineItem`` array from
the booking's ``price_breakdown`` and applies the tiered cancellation
policy.

Policy (Blue Ridge GA standard):

  >= 30 days before check-in:
      Refund all items where ``is_refundable == True``.

  14–29 days before check-in:
      50% of LODGING (type=rent) items,
      100% of the cleaning fee,
      Taxes recalculated on the refunded amount only.
      EXEMPT items (processing fees, ADW) return 0 cents.

  < 14 days before check-in:
      0 cents for lodging,
      100% of the cleaning fee,
      Taxes associated with the cleaning fee only.

All arithmetic is integer cents — no floating point.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

TAX_RATE_BPS = 1300  # 13% expressed as basis points (13 * 100)


def _cents(value: Any) -> int:
    """Coerce a value to integer cents, handling None and float."""
    if value is None:
        return 0
    return int(round(float(value)))


def _tax_on_cents(base_cents: int) -> int:
    """Calculate 13% tax on an amount in cents using integer math only."""
    return (base_cents * TAX_RATE_BPS + 5000) // 10000


def calculate_refund_ledger(
    reservation: Any,
    days_until_checkin: int,
) -> int:
    """
    Calculate the exact refund amount in integer cents using the Universal
    Ledger line items stored on the reservation.

    Falls back to the legacy column-based calculation when line items are
    not available on ``price_breakdown``.

    Returns:
        Total refund in integer cents (always >= 0).
    """
    price_breakdown = getattr(reservation, "price_breakdown", None) or {}
    line_items: list[dict] = price_breakdown.get("line_items", [])

    if line_items:
        return _calculate_from_line_items(line_items, days_until_checkin)

    return _calculate_from_columns(reservation, days_until_checkin)


def _calculate_from_line_items(
    line_items: list[dict],
    days_until_checkin: int,
) -> int:
    """Ledger-aware refund using stored LedgerLineItem dicts."""

    rent_cents = 0
    cleaning_cents = 0
    tax_cents = 0
    refundable_fee_cents = 0
    deposit_cents = 0

    for item in line_items:
        item_type = item.get("type", "")
        amount = _cents(item.get("amount_cents", 0))
        is_refundable = item.get("is_refundable", True)
        bucket = item.get("bucket", "lodging")
        name_lower = (item.get("name") or "").lower()

        if item_type == "rent":
            rent_cents += amount
        elif item_type == "tax":
            tax_cents += amount
        elif item_type == "deposit":
            if is_refundable:
                deposit_cents += amount
        elif item_type == "fee":
            if "clean" in name_lower:
                cleaning_cents += amount
            elif bucket == "exempt" or not is_refundable:
                pass  # processing fees, ADW — never refunded
            else:
                refundable_fee_cents += amount
        elif item_type == "addon":
            if is_refundable:
                refundable_fee_cents += amount

    # ── Tier 1: >= 30 days — full refund of all refundable items ──
    if days_until_checkin >= 30:
        refund = rent_cents + cleaning_cents + refundable_fee_cents + deposit_cents + tax_cents
        logger.info(
            "refund_tier1_full",
            days=days_until_checkin,
            refund_cents=refund,
        )
        return max(refund, 0)

    # ── Tier 2: 14-29 days — partial ──
    if days_until_checkin >= 14:
        lodging_refund = (rent_cents * 50 + 50) // 100  # 50% with rounding
        cleaning_refund = cleaning_cents
        taxable_refund_base = lodging_refund + cleaning_refund
        tax_refund = _tax_on_cents(taxable_refund_base)
        deposit_refund = deposit_cents

        refund = lodging_refund + cleaning_refund + tax_refund + deposit_refund
        logger.info(
            "refund_tier2_partial",
            days=days_until_checkin,
            lodging_refund_cents=lodging_refund,
            cleaning_refund_cents=cleaning_refund,
            tax_refund_cents=tax_refund,
            refund_cents=refund,
        )
        return max(refund, 0)

    # ── Tier 3: < 14 days — cleaning fee + associated taxes only ──
    cleaning_refund = cleaning_cents
    tax_refund = _tax_on_cents(cleaning_refund)
    deposit_refund = deposit_cents

    refund = cleaning_refund + tax_refund + deposit_refund
    logger.info(
        "refund_tier3_minimal",
        days=days_until_checkin,
        cleaning_refund_cents=cleaning_refund,
        tax_refund_cents=tax_refund,
        refund_cents=refund,
    )
    return max(refund, 0)


def _calculate_from_columns(
    reservation: Any,
    days_until_checkin: int,
) -> int:
    """
    Fallback refund calculation using Reservation model columns.

    Used for bookings that predate ledger-item persistence.
    """
    total_cents = _cents(
        (getattr(reservation, "total_amount", None) or 0) * 100
    )
    cleaning_cents = _cents(
        (getattr(reservation, "cleaning_fee", None) or 0) * 100
    )
    tax_cents = _cents(
        (getattr(reservation, "tax_amount", None) or 0) * 100
    )

    if days_until_checkin >= 30:
        return max(total_cents, 0)

    if days_until_checkin >= 14:
        pre_tax = total_cents - tax_cents
        lodging_base = pre_tax - cleaning_cents
        lodging_refund = (lodging_base * 50 + 50) // 100
        cleaning_refund = cleaning_cents
        tax_refund = _tax_on_cents(lodging_refund + cleaning_refund)
        return max(lodging_refund + cleaning_refund + tax_refund, 0)

    cleaning_refund = cleaning_cents
    tax_refund = _tax_on_cents(cleaning_refund)
    return max(cleaning_refund + tax_refund, 0)
