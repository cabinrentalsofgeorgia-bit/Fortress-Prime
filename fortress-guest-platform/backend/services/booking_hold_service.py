"""
Checkout hold lifecycle: advisory-locked hold row, Stripe PaymentIntent, convert to reservation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.event_publisher import publish_event
from backend.integrations.stripe_payments import StripePayments
from backend.models.guest import Guest
from backend.models.property import Property
from backend.models.reservation_hold import ReservationHold
from backend.services.booking_hold_errors import BookingHoldError
from backend.services.hold_service import create_inventory_hold
from backend.services.fast_quote_service import (
    FastQuoteError,
    build_quote_snapshot,
)
from backend.services.reservation_finalization_service import (
    FinalizeHoldResult,
    reservation_finalization_service,
)
from backend.services.sovereign_checkout_quote import validate_signed_quote_for_hold

logger = structlog.get_logger()

stripe_payments = StripePayments()


def _signed_quote_hold_error(code: str) -> BookingHoldError:
    mapping: dict[str, tuple[str, int]] = {
        "signed_quote_verification_misconfigured": (
            "Signed quote verification is not configured",
            500,
        ),
        "signed_quote_invalid_signature": ("Invalid signed quote signature", 403),
        "signed_quote_missing_expiry": ("Signed quote is missing expiry", 422),
        "signed_quote_invalid_expiry": ("Signed quote has invalid expiry", 422),
        "signed_quote_expired": ("Signed quote has expired", 410),
        "signed_quote_property_mismatch": ("Signed quote does not match this property", 422),
        "signed_quote_dates_mismatch": ("Signed quote does not match these dates", 422),
        "signed_quote_guests_mismatch": ("Signed quote does not match guest count", 422),
        "signed_quote_pets_mismatch": ("Signed quote does not match pet count", 422),
        "signed_quote_missing_line_items": ("Signed quote is missing line items", 422),
        "signed_quote_invalid_line_items": ("Signed quote has invalid line items", 422),
        "signed_quote_total_mismatch": ("Signed quote total does not match line items", 422),
    }
    message, status = mapping.get(code, ("Invalid signed quote", 422))
    return BookingHoldError(message, status)


async def _emit_reservation_confirmed(reservation: Any) -> None:
    await publish_event(
        "reservation.confirmed",
        {
            "reservation_id": str(reservation.id),
            "confirmation_code": reservation.confirmation_code,
            "property_id": str(reservation.property_id) if reservation.property_id else None,
            "guest_id": str(reservation.guest_id) if reservation.guest_id else None,
            "booking_source": reservation.booking_source,
            "status": reservation.status,
            "check_in_date": reservation.check_in_date.isoformat() if reservation.check_in_date else None,
            "check_out_date": reservation.check_out_date.isoformat() if reservation.check_out_date else None,
            "total_amount": float(reservation.total_amount or 0),
            "paid_amount": float(reservation.paid_amount or 0),
        },
        key=reservation.confirmation_code or str(reservation.id),
    )


async def create_checkout_hold(
    db: AsyncSession,
    *,
    property_id: UUID,
    check_in: date,
    check_out: date,
    session_id: str,
    num_guests: int,
    guest_first_name: str,
    guest_last_name: str,
    guest_email: str,
    guest_phone: str,
    special_requests: str | None = None,
    signed_quote: dict[str, Any] | None = None,
    pets: int = 0,
    adults: int | None = None,
    children: int | None = None,
    quote_ref: UUID | None = None,
) -> dict[str, Any]:
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise BookingHoldError("Property not found", 404)

    if settings.sovereign_quote_signing_enabled:
        if signed_quote is None:
            raise BookingHoldError("Signed quote is required for checkout", 422)
        try:
            validate_signed_quote_for_hold(
                signed_quote,
                property_id=property_id,
                check_in=check_in,
                check_out=check_out,
                num_guests=num_guests,
                pets=pets,
                secret=settings.sovereign_quote_signing_key,
            )
        except ValueError as exc:
            raise _signed_quote_hold_error(str(exc)) from exc
        snapshot = dict(signed_quote)
        total = Decimal(str(signed_quote["total"]))
    else:
        try:
            snapshot = await build_quote_snapshot(
                db,
                property_id,
                check_in,
                check_out,
                num_guests,
                adults=adults,
                children=children,
                pets=pets,
            )
        except FastQuoteError as exc:
            raise BookingHoldError(exc.message, exc.http_status) from exc
        total = Decimal(str(snapshot["total"]))

    # Embed quote_ref so it can be retrieved at confirm-hold time to link GuestQuote.
    if quote_ref is not None:
        snapshot["quote_ref"] = str(quote_ref)

    guest = None
    if guest_email:
        guest = (
            await db.execute(select(Guest).where(Guest.email == guest_email))
        ).scalar_one_or_none()
    if guest is None and guest_phone:
        guest = (
            await db.execute(select(Guest).where(Guest.phone_number == guest_phone))
        ).scalar_one_or_none()
    if guest is None:
        guest = Guest(
            email=guest_email,
            first_name=guest_first_name,
            last_name=guest_last_name,
            phone=guest_phone,
        )
        db.add(guest)
        await db.flush()
    else:
        guest.email = guest_email
        guest.first_name = guest_first_name
        guest.last_name = guest_last_name
        guest.phone = guest_phone
    total_cents = int((total * 100).to_integral_value())
    try:
        hold = await create_inventory_hold(
            db,
            property_id=property_id,
            check_in=check_in,
            check_out=check_out,
            session_id=session_id,
            guest_id=guest.id,
            num_guests=num_guests,
            amount_total=total,
            quote_snapshot=snapshot,
            special_requests=special_requests,
        )
    except HTTPException as exc:
        await db.rollback()
        raise BookingHoldError(str(exc.detail), exc.status_code) from exc

    try:
        payment = await stripe_payments.create_payment_intent(
            amount_cents=total_cents,
            reservation_id=str(hold.id),
            guest_email=guest_email,
            guest_name=f"{guest_first_name} {guest_last_name}",
            property_name=prop.name,
            extra_metadata={
                "hold_id": str(hold.id),
                "reservation_hold_id": str(hold.id),
                "property_id": str(property_id),
                "source": "direct_booking_hold",
            },
            idempotency_key=f"fortress_direct_hold_{hold.id}",
        )
    except Exception as exc:
        await db.rollback()
        logger.error("checkout_hold_stripe_failed", error=str(exc))
        raise BookingHoldError("Payment provider error", 502) from exc

    hold.payment_intent_id = payment["payment_intent_id"]
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise BookingHoldError("Property is not available for these dates", 409) from exc

    logger.info(
        "checkout_hold_created",
        hold_id=str(hold.id),
        property_id=str(property_id),
        payment_intent_id=hold.payment_intent_id,
    )

    if settings.streamline_sovereign_bridge_hold_enabled:
        try:
            from backend.services.sovereign_inventory_manager import sovereign_inventory_manager

            bridge = await sovereign_inventory_manager.hold_dates_for_property(
                db,
                property_id=property_id,
                check_in=check_in,
                check_out=check_out,
                note=f"SOVEREIGN_CHECKOUT_IN_PROGRESS hold_id={hold.id}",
            )
            logger.info(
                "checkout_hold_streamline_bridge",
                hold_id=str(hold.id),
                legacy_notified=bridge.legacy_notified,
                detail=bridge.detail,
            )
        except Exception as exc:
            logger.warning(
                "checkout_hold_streamline_bridge_failed",
                hold_id=str(hold.id),
                error=str(exc)[:200],
            )

    return {
        "hold_id": str(hold.id),
        "expires_at": hold.expires_at.isoformat(),
        "total_amount": float(total),
        "payment": payment,
    }


async def finalize_hold_as_reservation(
    db: AsyncSession,
    hold_id: UUID,
    *,
    require_succeeded_intent: bool = True,
) -> FinalizeHoldResult:
    """
    Convert an active hold to a confirmed reservation after the client confirms payment.

    Webhook finalization uses :func:`convert_hold_to_reservation` so both paths share
    :class:`~backend.services.reservation_finalization_service.ReservationFinalizationService`.
    """
    _ = require_succeeded_intent  # API compatibility; client path always verifies PI with Stripe.
    try:
        outcome = await reservation_finalization_service.finalize_by_hold_id(
            db,
            hold_id=hold_id,
            verification_mode="client",
        )
        if not outcome.already_finalized:
            await _emit_reservation_confirmed(outcome.reservation)
        return outcome
    except BookingHoldError:
        await db.rollback()
        raise


async def convert_hold_to_reservation(
    payment_intent_id: str,
    db: AsyncSession,
    *,
    metadata_hold_id: str | None = None,
) -> Any | None:
    """
    Convert the checkout hold for this PaymentIntent into a reservation.

    Returns ``None`` when no hold row matches the PaymentIntent id. Idempotent: if the hold
    was already converted (e.g. client confirm-hold won the race), returns the existing reservation.
    """
    normalized_payment_intent_id = (payment_intent_id or "").strip()
    if not normalized_payment_intent_id:
        raise BookingHoldError("Missing payment intent", 400)

    try:
        outcome = await reservation_finalization_service.finalize_by_payment_intent(
            db,
            payment_intent_id=normalized_payment_intent_id,
            metadata_hold_id=metadata_hold_id,
        )
        if outcome is None:
            return None
        await db.commit()
    except BookingHoldError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise BookingHoldError("Property is not available for these dates", 409) from exc

    reservation = outcome.reservation
    logger.info(
        "checkout_hold_converted_via_payment_intent",
        reservation_id=str(reservation.id),
        payment_intent_id=normalized_payment_intent_id,
        already_finalized=outcome.already_finalized,
    )
    if not outcome.already_finalized:
        await _emit_reservation_confirmed(reservation)
    return reservation


async def process_payment_intent_succeeded_for_hold(
    db: AsyncSession,
    payment_intent_id: str,
    *,
    metadata_hold_id: str | None = None,
) -> bool:
    """Idempotent webhook helper: find hold by PI id and finalize."""
    normalized_payment_intent_id = (payment_intent_id or "").strip()
    if not normalized_payment_intent_id:
        return False

    try:
        await convert_hold_to_reservation(
            normalized_payment_intent_id,
            db,
            metadata_hold_id=metadata_hold_id,
        )
    except BookingHoldError as exc:
        logger.warning(
            "hold_finalize_skipped",
            payment_intent_id=normalized_payment_intent_id,
            detail=str(exc),
        )
    return True
