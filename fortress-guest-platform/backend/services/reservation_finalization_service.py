"""
Central reconciliation for direct-booking checkout: client confirm-hold vs Stripe webhook race.

- hold_id (ReservationHold.id) is the idempotency anchor; the hold row is locked with SELECT FOR UPDATE.
- First finalizer commits the reservation and sets converted_reservation_id; the second returns the same reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from inspect import isawaitable
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from backend.core.config import settings
from backend.core.time import ensure_utc, utc_now
from backend.integrations.stripe_payments import StripePayments
from backend.models.guest import Guest
from backend.models.reservation import Reservation
from backend.models.reservation_hold import ReservationHold
from backend.services.booking_hold_errors import BookingHoldError
from backend.services.fast_quote_service import (
    FastQuoteError,
    acquire_property_booking_lock,
    assert_property_available_for_stay,
    expire_stale_holds,
)
from backend.services.reservation_engine import ReservationEngine

logger = structlog.get_logger()
stripe_client = StripePayments()
reservation_engine = ReservationEngine()

VerificationMode = Literal["client", "webhook"]


class _TransactionScope:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._context_manager: object | None = None
        self._owns_transaction = False

    async def __aenter__(self) -> object:
        if self._db.in_transaction():
            return self._db
        try:
            begin_result = self._db.begin()
            self._owns_transaction = True
            self._context_manager = await begin_result if isawaitable(begin_result) else begin_result
            return await self._context_manager.__aenter__()  # type: ignore[union-attr]
        except InvalidRequestError:
            # Some call sites trigger SQLAlchemy autobegin semantics before we enter
            # the explicit transaction scope. In that case, operate within the
            # existing transaction instead of failing the request.
            return self._db

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        if not self._owns_transaction or self._context_manager is None:
            return None
        return await self._context_manager.__aexit__(exc_type, exc, tb)  # type: ignore[union-attr]


def _transaction_scope(db: AsyncSession) -> _TransactionScope:
    return _TransactionScope(db)


def _payment_intent_succeeded(intent_id: str) -> bool:
    if not settings.stripe_secret_key:
        return False
    try:
        return stripe_client.retrieve_payment_intent_status(intent_id) == "succeeded"
    except Exception:
        return False


@dataclass(frozen=True)
class FinalizeHoldResult:
    """Outcome of a single finalization attempt (client or webhook)."""

    reservation: Any
    already_finalized: bool = False


class ReservationFinalizationService:
    """
    Single code path for converting an active checkout hold to a reservation.
    Callers must use either finalize_by_hold_id (client) or finalize_by_payment_intent (webhook).
    """

    async def finalize_by_hold_id(
        self,
        db: AsyncSession,
        *,
        hold_id: UUID,
        verification_mode: VerificationMode,
        stripe_payment_intent_id: str | None = None,
        metadata_hold_id: str | None = None,
    ) -> FinalizeHoldResult:
        stmt = (
            select(ReservationHold)
            .options(lazyload("*"))
            .where(ReservationHold.id == hold_id)
            .with_for_update()
        )
        async with _transaction_scope(db):
            result = await db.execute(stmt)
            hold = result.scalar_one_or_none()
            if hold is None:
                raise BookingHoldError("Hold not found", 404)
            return await self._finalize_locked_hold(
                db,
                hold,
                verification_mode=verification_mode,
                stripe_payment_intent_id=stripe_payment_intent_id,
                metadata_hold_id=metadata_hold_id,
            )

    async def finalize_by_payment_intent(
        self,
        db: AsyncSession,
        *,
        payment_intent_id: str,
        metadata_hold_id: str | None = None,
    ) -> FinalizeHoldResult | None:
        normalized = (payment_intent_id or "").strip()
        if not normalized:
            return None
        stmt = (
            select(ReservationHold)
            .options(lazyload("*"))
            .where(ReservationHold.payment_intent_id == normalized)
            .with_for_update()
        )
        async with _transaction_scope(db):
            result = await db.execute(stmt)
            hold = result.scalar_one_or_none()
            if hold is None:
                return None
            return await self._finalize_locked_hold(
                db,
                hold,
                verification_mode="webhook",
                stripe_payment_intent_id=normalized,
                metadata_hold_id=metadata_hold_id,
            )

    async def _finalize_locked_hold(
        self,
        db: AsyncSession,
        hold: ReservationHold,
        *,
        verification_mode: VerificationMode,
        stripe_payment_intent_id: str | None,
        metadata_hold_id: str | None,
    ) -> FinalizeHoldResult:
        if hold.status == "converted":
            if hold.converted_reservation_id is not None:
                reservation = await db.get(Reservation, hold.converted_reservation_id)
                if reservation is None:
                    logger.error(
                        "hold_converted_reservation_missing",
                        hold_id=str(hold.id),
                        converted_reservation_id=str(hold.converted_reservation_id),
                    )
                    raise BookingHoldError("Hold already finalized", 409)
                logger.info(
                    "checkout_hold_finalize_idempotent",
                    hold_id=str(hold.id),
                    reservation_id=str(reservation.id),
                    verification_mode=verification_mode,
                )
                return FinalizeHoldResult(reservation=reservation, already_finalized=True)
            logger.warning(
                "hold_converted_without_fk_legacy",
                hold_id=str(hold.id),
                payment_intent_id=hold.payment_intent_id,
            )
            raise BookingHoldError("Hold already finalized", 409)

        if hold.status == "expired":
            raise BookingHoldError("Hold expired", 410)
        if hold.status != "active":
            raise BookingHoldError("Hold is no longer active", 409)

        if metadata_hold_id is not None and str(metadata_hold_id).strip() != str(hold.id):
            raise BookingHoldError("Payment metadata does not match this hold", 400)

        normalized_pi = (stripe_payment_intent_id or "").strip()
        if verification_mode == "webhook":
            if not hold.payment_intent_id:
                raise BookingHoldError("Missing payment intent on hold", 400)
            if normalized_pi != hold.payment_intent_id.strip():
                raise BookingHoldError("Payment intent mismatch", 400)
        elif verification_mode == "client":
            if not hold.payment_intent_id:
                raise BookingHoldError("Missing payment intent", 400)
            if not _payment_intent_succeeded(hold.payment_intent_id):
                raise BookingHoldError("Payment not completed", 402)

        await acquire_property_booking_lock(db, hold.property_id)
        await expire_stale_holds(db)
        await db.refresh(hold)

        if hold.status == "converted":
            if hold.converted_reservation_id is not None:
                reservation = await db.get(Reservation, hold.converted_reservation_id)
                if reservation is None:
                    raise BookingHoldError("Hold already finalized", 409)
                return FinalizeHoldResult(reservation=reservation, already_finalized=True)
            raise BookingHoldError("Hold already finalized", 409)

        if hold.status == "expired":
            raise BookingHoldError("Hold expired", 410)
        if hold.status != "active":
            raise BookingHoldError("Hold is no longer active", 409)

        now = utc_now()
        expires_at = ensure_utc(hold.expires_at)
        if expires_at <= now:
            hold.status = "expired"
            hold.updated_at = now
            raise BookingHoldError("Hold expired", 410)

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
        admin_amt = snap.get("admin_fee")
        if admin_amt is not None:
            reservation.service_fee = Decimal(str(admin_amt))
        pet_amt = snap.get("pet_fee")
        if pet_amt is not None:
            reservation.pet_fee = Decimal(str(pet_amt))
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
        hold.converted_reservation_id = reservation.id
        hold.updated_at = now

        logger.info(
            "checkout_hold_confirmed",
            hold_id=str(hold.id),
            reservation_id=str(reservation.id),
            verification_mode=verification_mode,
        )
        return FinalizeHoldResult(reservation=reservation, already_finalized=False)


reservation_finalization_service = ReservationFinalizationService()
