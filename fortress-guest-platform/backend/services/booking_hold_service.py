"""
Checkout hold lifecycle: advisory-locked hold row, Stripe PaymentIntent, convert to reservation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from inspect import isawaitable
from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time import ensure_utc, utc_now
from backend.integrations.stripe_payments import StripePayments
from backend.models.guest import Guest
from backend.models.property import Property
from backend.models.reservation_hold import ReservationHold
from backend.services.hold_service import create_inventory_hold
from backend.services.fast_quote_service import (
    FastQuoteError,
    acquire_property_booking_lock,
    assert_property_available_for_stay,
    build_quote_snapshot,
    expire_stale_holds,
)
from backend.services.reservation_engine import ReservationEngine

logger = structlog.get_logger()

stripe_payments = StripePayments()
reservation_engine = ReservationEngine()


class BookingHoldError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class _TransactionScope:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._context_manager: object | None = None
        self._owns_transaction = False

    async def __aenter__(self) -> object:
        if self._db.in_transaction():
            return self._db
        begin_result = self._db.begin()
        self._owns_transaction = True
        self._context_manager = await begin_result if isawaitable(begin_result) else begin_result
        return await self._context_manager.__aenter__()  # type: ignore[union-attr]

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        if not self._owns_transaction or self._context_manager is None:
            return None
        return await self._context_manager.__aexit__(exc_type, exc, tb)  # type: ignore[union-attr]


def _transaction_scope(db: AsyncSession) -> _TransactionScope:
    return _TransactionScope(db)


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
) -> dict[str, Any]:
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise BookingHoldError("Property not found", 404)

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

    try:
        snapshot = await build_quote_snapshot(db, property_id, check_in, check_out, num_guests)
    except FastQuoteError as exc:
        await db.rollback()
        raise BookingHoldError(exc.message, exc.http_status) from exc
    total = Decimal(str(snapshot["total"]))
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
                "reservation_hold_id": str(hold.id),
                "property_id": str(property_id),
                "source": "direct_booking_hold",
            },
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

    return {
        "hold_id": str(hold.id),
        "expires_at": hold.expires_at.isoformat(),
        "total_amount": float(total),
        "payment": payment,
    }


def _payment_intent_succeeded(intent_id: str) -> bool:
    if not settings.stripe_secret_key:
        return False
    try:
        return stripe_payments.retrieve_payment_intent_status(intent_id) == "succeeded"
    except Exception:
        return False


async def finalize_hold_as_reservation(
    db: AsyncSession,
    hold_id: UUID,
    *,
    require_succeeded_intent: bool = True,
) -> Any:
    """
    Convert an active hold to a confirmed reservation after payment succeeds.
    Caller should ensure Stripe intent is paid when require_succeeded_intent is True.
    """
    reservation: Any | None = None
    pending_error: BookingHoldError | None = None

    try:
        async with _transaction_scope(db):
            hold = await db.get(ReservationHold, hold_id)
            if hold is None:
                raise BookingHoldError("Hold not found", 404)

            await acquire_property_booking_lock(db, hold.property_id)
            await expire_stale_holds(db)

            hold = await db.get(ReservationHold, hold_id)
            if hold is None or hold.status != "active":
                raise BookingHoldError("Hold is no longer active", 409)

            now = utc_now()
            expires_at = ensure_utc(hold.expires_at)
            if expires_at <= now:
                hold.status = "expired"
                hold.updated_at = now
                pending_error = BookingHoldError("Hold expired", 410)
            elif require_succeeded_intent and not hold.payment_intent_id:
                raise BookingHoldError("Missing payment intent", 400)
            elif require_succeeded_intent and not _payment_intent_succeeded(hold.payment_intent_id):
                raise BookingHoldError("Payment not completed", 402)
            else:
                try:
                    await assert_property_available_for_stay(
                        db,
                        hold.property_id,
                        hold.check_in_date,
                        hold.check_out_date,
                        exclude_hold_id=hold.id,
                    )
                except FastQuoteError as exc:
                    raise BookingHoldError(exc.message, exc.http_status) from exc

                snap = hold.quote_snapshot or {}
                total_amount = Decimal(str(snap.get("total", hold.amount_total or "0")))
                guest = await db.get(Guest, hold.guest_id) if hold.guest_id else None

                try:
                    reservation = await reservation_engine.create_reservation(
                        db,
                        {
                            "guest_id": hold.guest_id,
                            "property_id": hold.property_id,
                            "check_in_date": hold.check_in_date,
                            "check_out_date": hold.check_out_date,
                            "num_guests": hold.num_guests,
                            "booking_source": "direct",
                            "total_amount": total_amount,
                            "internal_notes": hold.special_requests,
                            "exclude_hold_id": hold.id,
                        },
                    )
                except ValueError as exc:
                    raise BookingHoldError(str(exc), 409) from exc
                except IntegrityError as exc:
                    raise BookingHoldError("Property is not available for these dates", 409) from exc

                rent = snap.get("rent")
                cleaning = snap.get("cleaning")
                taxes = snap.get("taxes")
                if rent is not None:
                    reservation.nightly_rate = Decimal(str(rent)) / max(
                        1, (hold.check_out_date - hold.check_in_date).days
                    )
                if cleaning is not None:
                    reservation.cleaning_fee = Decimal(str(cleaning))
                if taxes is not None:
                    reservation.tax_amount = Decimal(str(taxes))
                reservation.price_breakdown = snap
                reservation.special_requests = hold.special_requests
                reservation.guest_email = guest.email if guest is not None else reservation.guest_email
                reservation.guest_name = guest.full_name if guest is not None else reservation.guest_name
                reservation.guest_phone = guest.phone if guest is not None else reservation.guest_phone
                reservation.paid_amount = total_amount
                reservation.balance_due = Decimal("0.00")

                hold.status = "converted"
                hold.updated_at = now
    except BookingHoldError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise BookingHoldError("Property is not available for these dates", 409) from exc

    if pending_error is not None:
        raise pending_error
    if reservation is None:
        raise BookingHoldError("Hold conversion failed", 500)

    logger.info(
        "checkout_hold_confirmed",
        hold_id=str(hold_id),
        reservation_id=str(reservation.id),
    )

    return reservation


async def convert_hold_to_reservation(
    payment_intent_id: str,
    db: AsyncSession,
) -> Any | None:
    """
    Convert the active checkout hold associated with a Stripe PaymentIntent
    into a permanent reservation. Returns None when no matching active hold exists.
    """
    normalized_payment_intent_id = (payment_intent_id or "").strip()
    if not normalized_payment_intent_id:
        raise BookingHoldError("Missing payment intent", 400)

    hold_result = await db.execute(
        select(ReservationHold).where(ReservationHold.payment_intent_id == normalized_payment_intent_id)
    )
    hold = hold_result.scalar_one_or_none()
    if hold is None:
        return None
    if hold.status != "active":
        return None

    try:
        reservation = await finalize_hold_as_reservation(
            db,
            hold.id,
            require_succeeded_intent=False,
        )
        await db.commit()
    except BookingHoldError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise BookingHoldError("Property is not available for these dates", 409) from exc

    logger.info(
        "checkout_hold_converted_via_payment_intent",
        hold_id=str(hold.id),
        reservation_id=str(reservation.id),
        payment_intent_id=normalized_payment_intent_id,
    )
    return reservation


async def process_payment_intent_succeeded_for_hold(
    db: AsyncSession,
    payment_intent_id: str,
) -> bool:
    """Idempotent webhook handler: find hold by PI id and finalize."""
    normalized_payment_intent_id = (payment_intent_id or "").strip()
    if not normalized_payment_intent_id:
        return False

    result = await db.execute(
        select(ReservationHold).where(ReservationHold.payment_intent_id == normalized_payment_intent_id)
    )
    hold = result.scalar_one_or_none()
    if hold is None:
        return False
    if hold.status != "active":
        return True
    try:
        await convert_hold_to_reservation(normalized_payment_intent_id, db)
    except BookingHoldError as exc:
        logger.warning(
            "hold_finalize_skipped",
            hold_id=str(hold.id),
            detail=str(exc),
        )
    return True
