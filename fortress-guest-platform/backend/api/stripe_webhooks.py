"""
Stripe Webhooks — Autonomous Fiduciary Clearing Engine.

**Canonical module path:** ``backend/api/stripe_webhooks.py`` (not ``webhooks_stripe.py``).

True Path — direct booking settlement (Strike 20)
===================================================
There is **no** separate ``SovereignBooking`` / ``booking_ledger`` table. Financial finality on
sovereign Postgres is:

  ``ReservationHold`` (active checkout hold) → ``Reservation`` (settled booking)

driven by :func:`~backend.services.booking_hold_service.convert_hold_to_reservation` and
:class:`~backend.services.reservation_finalization_service.ReservationFinalizationService`.

- ``payment_intent.succeeded`` with ``metadata.source == direct_booking_hold`` runs that conversion.
- ``strike20_settlement_orphan``: no hold row for the PaymentIntent → **HTTP 200** + warning log
  (avoids Stripe retry storms for unrelated dashboard charges).
- Streamline sync is **secondary**: gated by ``STREAMLINE_SOVEREIGN_BRIDGE_SETTLEMENT_ENABLED`` and
  ``STREAMLINE_SOVEREIGN_BRIDGE_RESERVATION_METHOD``. On unexpected errors after settlement,
  :meth:`~backend.services.sovereign_inventory_manager.SovereignInventoryManager.queue_strike20_settlement_for_reconciliation`
  best-effort enqueues ``deferred_api_writes`` for the reconciliation worker (same envelope as
  circuit-open Streamline writes).

Also handles checkout.session.completed events from Stripe Payment Links for Capital Calls
and guest quotes.

Dual-journal commit (capex path):
  Journal 1 (Deposit):  DR 1010 Cash / CR 2000 Owner Trust
  Journal 2 (Expense):  DR 2000 Owner Trust / CR 2100 AP / CR 4100 PM Revenue
"""
import stripe
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments
from backend.services.booking_hold_service import BookingHoldError, convert_hold_to_reservation

logger = structlog.get_logger()
router = APIRouter()


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Verifies Stripe signature and dispatches by event type.

    Direct booking: ``payment_intent.succeeded`` + ``direct_booking_hold`` converts
    ``ReservationHold`` → ``Reservation`` (sovereign ledger); Streamline bridge optional.
    """
    payload = await request.body()

    stripe_client = StripePayments()
    try:
        event = await stripe_client.handle_webhook(payload, stripe_signature or "")
    except stripe.error.SignatureVerificationError:
        logger.error("stripe_webhook_signature_invalid")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.error("stripe_webhook_construct_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    event_type = event.get("type", "")
    logger.info("stripe_webhook_received", event_type=event_type)

    if event_type == "payment_intent.succeeded":
        obj = event["data"]["object"]
        metadata = obj.get("metadata") or {}
        if metadata.get("source") == "direct_booking_hold":
            payment_intent_id = str(obj.get("id") or "").strip()
            meta_hold = metadata.get("hold_id") or metadata.get("reservation_hold_id")
            meta_hold = str(meta_hold).strip() if meta_hold else None
            if payment_intent_id:
                try:
                    reservation = await convert_hold_to_reservation(
                        payment_intent_id,
                        db,
                        metadata_hold_id=meta_hold,
                    )
                except BookingHoldError as exc:
                    logger.warning(
                        "direct_booking_hold_conversion_rejected",
                        payment_intent_id=payment_intent_id,
                        detail=str(exc),
                    )
                    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
                if reservation is None:
                    logger.warning(
                        "strike20_settlement_orphan",
                        payment_intent_id=payment_intent_id,
                        metadata_hold_id=meta_hold,
                        message="No matching active hold for this PaymentIntent",
                    )
                else:
                    logger.info(
                        "strike20_settlement_confirmed",
                        payment_intent_id=payment_intent_id,
                        hold_id=meta_hold,
                        reservation_id=str(reservation.id),
                    )
                    if settings.streamline_sovereign_bridge_settlement_enabled:
                        from backend.services.sovereign_inventory_manager import (
                            sovereign_inventory_manager,
                        )

                        try:
                            bridge = await sovereign_inventory_manager.finalize_legacy_reservation(
                                db,
                                reservation_id=reservation.id,
                                stripe_payment_intent_id=payment_intent_id,
                            )
                            logger.info(
                                "strike20_legacy_sync_attempt",
                                reservation_id=str(reservation.id),
                                legacy_notified=bridge.legacy_notified,
                                detail=bridge.detail,
                            )
                        except Exception as exc:
                            logger.warning(
                                "strike20_legacy_sync_deferred",
                                reservation_id=str(reservation.id),
                                error=str(exc)[:300],
                            )
                            qid = await sovereign_inventory_manager.queue_strike20_settlement_for_reconciliation(
                                db,
                                reservation_id=reservation.id,
                                stripe_payment_intent_id=payment_intent_id,
                                failure_reason=str(exc)[:500],
                            )
                            if qid > 0:
                                logger.info(
                                    "strike20_settlement_replay_queued_from_webhook",
                                    deferred_api_write_id=qid,
                                    reservation_id=str(reservation.id),
                                )
                logger.info(
                    "direct_booking_hold_finalized_via_stripe_webhook",
                    payment_intent_id=payment_intent_id,
                    hold_id=meta_hold,
                    reservation_id=str(reservation.id) if reservation is not None else None,
                    converted=reservation is not None,
                )
            return {"status": "ok", "event_type": event_type}

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]

        guest_quote_id = (session.get("metadata") or {}).get("guest_quote_id")
        if guest_quote_id:
            await _process_guest_quote_payment(guest_quote_id, session, db)
        else:
            staging_id = await _extract_capex_staging_id(session)
            if staging_id is not None:
                await _process_capital_call_funding(staging_id, session, db)

    return {"status": "ok"}


async def _process_guest_quote_payment(
    guest_quote_id: str,
    session: dict,
    db: AsyncSession,
) -> None:
    """Mark a GuestQuote as accepted after Stripe checkout completes."""
    from backend.models.vrs_quotes import GuestQuote
    from sqlalchemy import select

    try:
        result = await db.execute(
            select(GuestQuote).where(GuestQuote.id == guest_quote_id)
        )
        quote = result.scalar_one_or_none()
        if not quote:
            logger.warning("guest_quote_webhook_not_found", guest_quote_id=guest_quote_id)
            return

        if quote.status != "pending":
            logger.info(
                "guest_quote_webhook_already_processed",
                guest_quote_id=guest_quote_id,
                current_status=quote.status,
            )
            return

        quote.status = "accepted"
        await db.commit()

        logger.info(
            "guest_quote_payment_accepted",
            guest_quote_id=guest_quote_id,
            stripe_session_id=session.get("id", ""),
            amount_total=(session.get("amount_total") or 0) / 100.0,
        )
    except Exception as exc:
        await db.rollback()
        logger.error(
            "guest_quote_webhook_processing_failed",
            guest_quote_id=guest_quote_id,
            error=str(exc)[:300],
        )


async def _extract_capex_staging_id(session: dict) -> int | None:
    """
    Extract capex_staging_id from the Stripe event. PaymentLink metadata
    is not automatically copied to the checkout session, so we retrieve
    the PaymentLink object. Falls back to session.metadata.
    """
    staging_raw = session.get("metadata", {}).get("capex_staging_id")
    if staging_raw:
        return int(staging_raw)

    payment_link_id = session.get("payment_link")
    if payment_link_id:
        try:
            link = stripe.PaymentLink.retrieve(payment_link_id)
            staging_raw = link.get("metadata", {}).get("capex_staging_id")
            if staging_raw:
                return int(staging_raw)
        except Exception as exc:
            logger.warning(
                "stripe_webhook_payment_link_fetch_failed",
                payment_link_id=payment_link_id,
                error=str(exc),
            )

    return None


async def _process_capital_call_funding(
    staging_id: int,
    session: dict,
    db: AsyncSession,
):
    """
    Execute the dual-journal commit to clear a Capital Call.
    Idempotent: skips if the staging row is not PENDING_CAPEX_APPROVAL.
    """
    amount_paid = (session.get("amount_total") or 0) / 100.0

    try:
        row = await db.execute(
            text("""
                SELECT id, property_id, vendor, amount, total_owner_charge,
                       compliance_status, audit_trail
                FROM capex_staging WHERE id = :sid
            """),
            {"sid": staging_id},
        )
        item = row.fetchone()

        if not item:
            logger.warning("capex_webhook_staging_not_found", staging_id=staging_id)
            return

        if item.compliance_status != "PENDING_CAPEX_APPROVAL":
            logger.info(
                "capex_webhook_already_processed",
                staging_id=staging_id,
                current_status=item.compliance_status,
            )
            return

        vendor_cost = float(item.amount)
        total_owner_charge = float(item.total_owner_charge)
        pm_markup = round(total_owner_charge - vendor_cost, 2)

        if round(amount_paid, 2) != round(total_owner_charge, 2):
            logger.error(
                "capex_webhook_amount_mismatch",
                staging_id=staging_id,
                expected=total_owner_charge,
                received=amount_paid,
            )
            return

        idempotency_ref_deposit = f"CAPEX-{staging_id}"
        idempotency_ref_expense = f"CAPEX-EXP-{staging_id}"

        existing = await db.execute(
            text("""
                SELECT id FROM journal_entries
                WHERE reference_id IN (:ref1, :ref2)
                LIMIT 1
            """),
            {"ref1": idempotency_ref_deposit, "ref2": idempotency_ref_expense},
        )
        if existing.fetchone():
            logger.info(
                "capex_webhook_journal_exists",
                staging_id=staging_id,
            )
            return

        # --- Journal 1: Owner Deposit (DR Cash, CR Owner Trust) ---
        je_dep = await db.execute(
            text("""
                INSERT INTO journal_entries
                    (property_id, entry_date, description, reference_type, reference_id)
                VALUES
                    (:pid, CURRENT_DATE,
                     'Capital Call Funded via Stripe',
                     'capital_call_deposit', :ref)
                RETURNING id
            """),
            {"pid": item.property_id, "ref": idempotency_ref_deposit},
        )
        dep_id = je_dep.scalar()

        await db.execute(
            text("""
                INSERT INTO journal_line_items
                    (journal_entry_id, account_id, debit, credit)
                VALUES
                    (:je, (SELECT id FROM accounts WHERE code = '1010'), :amt, 0),
                    (:je, (SELECT id FROM accounts WHERE code = '2000'), 0, :amt)
            """),
            {"je": dep_id, "amt": total_owner_charge},
        )

        # --- Journal 2: CapEx Expense (DR Owner Trust, CR AP, CR PM Rev) ---
        je_exp = await db.execute(
            text("""
                INSERT INTO journal_entries
                    (property_id, entry_date, description, reference_type, reference_id)
                VALUES
                    (:pid, CURRENT_DATE,
                     :desc,
                     'expense', :ref)
                RETURNING id
            """),
            {
                "pid": item.property_id,
                "desc": f"CapEx Executed: {item.vendor}",
                "ref": idempotency_ref_expense,
            },
        )
        exp_id = je_exp.scalar()

        await db.execute(
            text("""
                INSERT INTO journal_line_items
                    (journal_entry_id, account_id, debit, credit)
                VALUES
                    (:je, (SELECT id FROM accounts WHERE code = '2000'), :total, 0),
                    (:je, (SELECT id FROM accounts WHERE code = '2100'), 0, :vendor),
                    (:je, (SELECT id FROM accounts WHERE code = '4100'), 0, :markup)
            """),
            {"je": exp_id, "total": total_owner_charge, "vendor": vendor_cost, "markup": pm_markup},
        )

        # --- Clear the staging flag ---
        import json
        from datetime import datetime, timezone

        audit = item.audit_trail or {}
        audit["funded_via"] = "stripe_webhook"
        audit["funded_at"] = datetime.now(timezone.utc).isoformat()
        audit["amount_paid"] = amount_paid
        audit["stripe_session_id"] = session.get("id", "")
        audit["deposit_journal_entry_id"] = dep_id
        audit["expense_journal_entry_id"] = exp_id

        await db.execute(
            text("""
                UPDATE capex_staging
                SET compliance_status = 'APPROVED',
                    approved_at = CURRENT_TIMESTAMP,
                    approved_by = 'stripe_webhook',
                    audit_trail = :trail
                WHERE id = :sid
            """),
            {"sid": staging_id, "trail": json.dumps(audit)},
        )

        await db.commit()

        logger.info(
            "capex_capital_call_cleared",
            staging_id=staging_id,
            property_id=item.property_id,
            vendor=item.vendor,
            amount_paid=amount_paid,
            deposit_je=dep_id,
            expense_je=exp_id,
        )

    except Exception as exc:
        await db.rollback()
        logger.error(
            "capex_webhook_processing_failed",
            staging_id=staging_id,
            error=str(exc),
        )
