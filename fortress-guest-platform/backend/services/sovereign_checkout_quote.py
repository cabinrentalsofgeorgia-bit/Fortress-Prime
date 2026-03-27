"""
Issue and validate sealed sovereign quotes for checkout holds.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time import ensure_utc, utc_now
from backend.services.fast_quote_service import compute_fast_quote_breakdown
from backend.services.hold_service import HOLD_TTL_MINUTES
from backend.services.sovereign_quote_service import total_from_line_items
from backend.services.sovereign_quote_signing import build_signed_quote, verify_signed_quote


async def issue_signed_checkout_quote(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    adults: int | None,
    children: int | None,
    pets: int,
    signing_secret: str,
) -> dict[str, Any]:
    """Build canonical quote fields and HMAC signature (empty sig if secret unset)."""
    breakdown = await compute_fast_quote_breakdown(
        db,
        property_id,
        check_in,
        check_out,
        guests,
        adults=adults,
        children=children,
        pets=pets,
    )
    eff_adults, eff_children = _party_for_payload(
        guests,
        adults,
        children,
    )
    issued_at = utc_now()
    expires_at = issued_at + timedelta(minutes=HOLD_TTL_MINUTES)
    line_items = [dict(row) for row in breakdown.line_items]
    computed_total = total_from_line_items(line_items)
    if computed_total != breakdown.total.quantize(Decimal("0.01")):
        raise ValueError("sovereign_quote_internal_total_mismatch")

    payload_wo_sig: dict[str, Any] = {
        "v": 1,
        "property_id": str(property_id),
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "guests": guests,
        "adults": eff_adults,
        "children": eff_children,
        "pets": pets,
        "currency": "USD",
        "pricing_source": breakdown.pricing_source,
        "line_items": line_items,
        "rent": str(breakdown.rent.quantize(Decimal("0.01"))),
        "cleaning": str(breakdown.cleaning.quantize(Decimal("0.01"))),
        "admin_fee": str(breakdown.admin_fee.quantize(Decimal("0.01"))),
        "pet_fee": str(breakdown.pet_fee.quantize(Decimal("0.01"))),
        "taxes": str(breakdown.taxes.quantize(Decimal("0.01"))),
        "total": str(breakdown.total.quantize(Decimal("0.01"))),
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    return build_signed_quote(payload_wo_sig, signing_secret)


def _party_for_payload(
    guests: int,
    adults: int | None,
    children: int | None,
) -> tuple[int, int]:
    if adults is None and children is None:
        a = max(1, guests)
        c = max(0, guests - a)
        return a, c
    assert adults is not None and children is not None
    return adults, children


def validate_signed_quote_for_hold(
    signed_quote: dict[str, Any],
    *,
    property_id: UUID,
    check_in: date,
    check_out: date,
    num_guests: int,
    pets: int,
    secret: str,
) -> None:
    """
    Fail closed unless the payload is authentic, unexpired, and matches the checkout request.

    Raises ``ValueError`` with a stable message prefix for HTTP mapping.
    """
    if not secret.strip():
        raise ValueError("signed_quote_verification_misconfigured")
    if not verify_signed_quote(signed_quote, secret):
        raise ValueError("signed_quote_invalid_signature")

    exp_raw = signed_quote.get("expires_at")
    if not exp_raw:
        raise ValueError("signed_quote_missing_expiry")
    exp_str = str(exp_raw).replace("Z", "+00:00")
    try:
        exp_dt = datetime.fromisoformat(exp_str)
    except ValueError as exc:
        raise ValueError("signed_quote_invalid_expiry") from exc
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    if ensure_utc(exp_dt) <= utc_now():
        raise ValueError("signed_quote_expired")

    if str(signed_quote.get("property_id") or "") != str(property_id):
        raise ValueError("signed_quote_property_mismatch")
    if str(signed_quote.get("check_in") or "") != check_in.isoformat():
        raise ValueError("signed_quote_dates_mismatch")
    if str(signed_quote.get("check_out") or "") != check_out.isoformat():
        raise ValueError("signed_quote_dates_mismatch")
    if int(signed_quote.get("guests") or 0) != int(num_guests):
        raise ValueError("signed_quote_guests_mismatch")
    if int(signed_quote.get("pets") or 0) != int(pets):
        raise ValueError("signed_quote_pets_mismatch")

    raw_items = signed_quote.get("line_items")
    if not isinstance(raw_items, list):
        raise ValueError("signed_quote_missing_line_items")
    line_items = []
    for row in raw_items:
        if not isinstance(row, dict):
            raise ValueError("signed_quote_invalid_line_items")
        line_items.append(
            {
                "type": str(row.get("type", "")),
                "description": str(row.get("description", "")),
                "amount": str(row.get("amount", "")),
            }
        )
    declared = Decimal(str(signed_quote.get("total") or "0")).quantize(Decimal("0.01"))
    computed = total_from_line_items(line_items)
    if computed != declared:
        raise ValueError("signed_quote_total_mismatch")
