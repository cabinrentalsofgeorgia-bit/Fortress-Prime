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
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments
from backend.models.reservation import Reservation
from backend.models.reservation_hold import ReservationHold
from backend.services.booking_hold_service import BookingHoldError, convert_hold_to_reservation
from backend.services.openshell_audit import record_audit_event

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
        source = metadata.get("source", "")

        if source == "direct_booking_hold":
            payment_intent_id = str(obj.get("id") or "").strip()
            meta_hold = metadata.get("hold_id") or metadata.get("reservation_hold_id")
            meta_hold = str(meta_hold).strip() if meta_hold else None
            if payment_intent_id:
                # ── Idempotency pre-check ────────────────────────────────────────────
                # If the hold is already converted (status == "converted" +
                # converted_reservation_id set), this is a Stripe retry of a
                # successfully settled payment. Return 200 immediately — the same
                # response Stripe received the first time — so it stops retrying.
                # Without this guard the handler raises HTTP 409, which Stripe treats
                # as a transient error and retries indefinitely.
                _hold_status = await db.scalar(
                    select(ReservationHold.status).where(
                        ReservationHold.payment_intent_id == payment_intent_id
                    )
                )
                if _hold_status == "converted":
                    logger.info(
                        "direct_booking_already_processed",
                        payment_intent_id=payment_intent_id,
                    )
                    return {"event_type": event_type, "status": "already_processed"}
                # ────────────────────────────────────────────────────────────────────

                try:
                    reservation = await convert_hold_to_reservation(
                        payment_intent_id,
                        db,
                        metadata_hold_id=meta_hold,
                    )
                except BookingHoldError as exc:
                    # "Hold already finalized" means a race was won by the client-side
                    # confirm flow or a concurrent webhook delivery. Treat as success so
                    # Stripe does not retry (HTTP 409 triggers retries).
                    if "already finalized" in str(exc).lower():
                        logger.info(
                            "direct_booking_already_processed",
                            payment_intent_id=payment_intent_id,
                            detail=str(exc),
                        )
                        return {"event_type": event_type, "status": "already_processed"}
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

        if source == "storefront_checkout":
            await _process_storefront_settlement(obj, metadata, db)
            return {"status": "ok", "event_type": event_type}

    if event_type == "invoice.paid":
        invoice_obj = event["data"]["object"]
        await _process_invoice_paid(invoice_obj, db)
        return {"status": "ok", "event_type": event_type}

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]

        if await _process_crog_vrs_reservation_payment_link(session, db):
            return {"status": "ok", "event_type": event_type, "handler": "crog_vrs_reservation_payment"}

        guest_quote_id = (session.get("metadata") or {}).get("guest_quote_id")
        if guest_quote_id:
            await _process_guest_quote_payment(guest_quote_id, session, db)
        else:
            staging_id = await _extract_capex_staging_id(session)
            if staging_id is not None:
                await _process_capital_call_funding(staging_id, session, db)

    return {"status": "ok"}


def _stringish(value: object) -> str:
    return str(value or "").strip()


def _stripe_id(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _stringish(value.get("id"))
    return _stringish(getattr(value, "id", ""))


async def _crog_vrs_payment_link_metadata(session: dict) -> dict[str, str]:
    """Return Payment Link metadata when this session belongs to CROG-VRS reservation payment."""
    session_metadata = dict(session.get("metadata") or {})
    payment_link_id = _stripe_id(session.get("payment_link"))
    link_metadata: dict[str, str] = {}
    if payment_link_id:
        try:
            payment_link = stripe.PaymentLink.retrieve(payment_link_id)
            link_metadata = dict(payment_link.get("metadata") or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "crog_vrs_payment_link_metadata_fetch_failed",
                payment_link_id=payment_link_id,
                error=str(exc)[:300],
            )

    merged = {**link_metadata, **session_metadata}
    if payment_link_id:
        merged.setdefault("payment_link_id", payment_link_id)
    return {str(key): str(value) for key, value in merged.items() if value is not None}


async def _record_crog_vrs_payment_reconciliation_audit(
    *,
    db: AsyncSession,
    reservation: Reservation | None,
    metadata: dict[str, str],
    session: dict,
    outcome: str,
    detail: str,
    expected_amount_cents: int | None,
    received_amount_cents: int,
) -> None:
    reservation_id = str(reservation.id) if reservation else metadata.get("reservation_id")
    breakdown = reservation.price_breakdown if reservation and isinstance(reservation.price_breakdown, dict) else {}
    await record_audit_event(
        db=db,
        actor_id="stripe_webhook",
        actor_email="stripe-webhook@crog-ai.com",
        action="quote_booking.stage_reservation_payment_reconciliation",
        resource_type="quote_booking_control_item",
        resource_id=f"reservation:{reservation_id}" if reservation_id else "reservation:unknown",
        purpose="Stripe-hosted payment signal staged for staff approval before local reservation payment posting.",
        tool_name="stripe_webhook",
        redaction_status="metadata_only",
        model_route="stripe_webhook",
        outcome=outcome,
        metadata_json={
            "reservation_id": reservation_id,
            "confirmation_code": metadata.get("confirmation_code") or (reservation.confirmation_code if reservation else None),
            "quote_id": metadata.get("quote_id") or breakdown.get("quote_ref"),
            "hold_id": metadata.get("hold_id") or breakdown.get("hold_ref"),
            "payment_link_id": metadata.get("payment_link_id") or _stripe_id(session.get("payment_link")),
            "checkout_session_id": session.get("id"),
            "payment_intent_id": _stripe_id(session.get("payment_intent")),
            "payment_status": session.get("payment_status"),
            "expected_amount_cents": expected_amount_cents,
            "received_amount_cents": received_amount_cents,
            "detail": detail,
            "requires_staff_approval": True,
            "local_payment_posted": False,
            "reservation_status_after": reservation.status if reservation else None,
            "paid_amount_after": str(reservation.paid_amount) if reservation else None,
            "balance_due_after": str(reservation.balance_due) if reservation else None,
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
        },
    )


async def _process_crog_vrs_reservation_payment_link(session: dict, db: AsyncSession) -> bool:
    """Stage CROG-VRS reservation payment signals without posting local payment automatically."""
    metadata = await _crog_vrs_payment_link_metadata(session)
    if metadata.get("type") != "crog_vrs_reservation_payment":
        return False

    received_amount_cents = int(session.get("amount_total") or session.get("amount_subtotal") or 0)
    payment_status = _stringish(session.get("payment_status"))
    payment_link_id = metadata.get("payment_link_id") or _stripe_id(session.get("payment_link"))
    session_id = _stringish(session.get("id"))
    payment_intent_id = _stripe_id(session.get("payment_intent"))
    reservation_id_raw = metadata.get("reservation_id")
    reservation: Reservation | None = None

    if reservation_id_raw:
        try:
            reservation = await db.get(Reservation, UUID(reservation_id_raw))
        except Exception:  # noqa: BLE001
            reservation = None

    if reservation is None:
        logger.warning(
            "crog_vrs_reservation_payment_orphan",
            reservation_id=reservation_id_raw,
            payment_link_id=payment_link_id,
            checkout_session_id=session_id,
        )
        await _record_crog_vrs_payment_reconciliation_audit(
            db=db,
            reservation=None,
            metadata=metadata,
            session=session,
            outcome="blocked",
            detail="Stripe payment session referenced a CROG-VRS reservation that was not found.",
            expected_amount_cents=None,
            received_amount_cents=received_amount_cents,
        )
        return True

    breakdown = dict(reservation.price_breakdown or {})
    existing_session_id = _stringish(breakdown.get("control_tower_payment_reconciliation_session_id"))
    existing_state = _stringish(breakdown.get("control_tower_payment_reconciliation_state"))
    if existing_session_id and existing_session_id == session_id and existing_state:
        logger.info(
            "crog_vrs_reservation_payment_already_staged",
            reservation_id=str(reservation.id),
            checkout_session_id=session_id,
            state=existing_state,
        )
        return True

    expected_payment_link_id = _stringish(breakdown.get("control_tower_payment_link_id"))
    expected_amount_raw = breakdown.get("control_tower_payment_amount_cents")
    expected_amount_cents = int(expected_amount_raw) if expected_amount_raw is not None else None

    now_iso = datetime.now(timezone.utc).isoformat()
    detail = "Stripe payment observed and staged for staff approval."
    outcome = "success"
    reconciliation_state = "stripe_paid_pending_staff_approval"

    if metadata.get("safe_staff_approved") != "true":
        outcome = "blocked"
        reconciliation_state = "unsafe_metadata_needs_staff_review"
        detail = "Payment Link metadata did not include the staff-approved safety flag."
    elif expected_payment_link_id and payment_link_id and expected_payment_link_id != payment_link_id:
        outcome = "blocked"
        reconciliation_state = "payment_link_mismatch_needs_staff_review"
        detail = "Stripe payment link id does not match the reservation payment handoff link."
    elif payment_status != "paid":
        outcome = "blocked"
        reconciliation_state = "stripe_unpaid_needs_staff_review"
        detail = f"Stripe checkout session completed with payment_status={payment_status or 'unknown'}."
    elif expected_amount_cents is not None and received_amount_cents != expected_amount_cents:
        outcome = "blocked"
        reconciliation_state = "amount_mismatch_needs_staff_review"
        detail = "Stripe paid amount does not match the reservation balance handoff amount."

    breakdown.update(
        {
            "control_tower_payment_reconciliation_state": reconciliation_state,
            "control_tower_payment_reconciliation_detail": detail,
            "control_tower_payment_reconciled_at": now_iso,
            "control_tower_payment_reconciliation_session_id": session_id,
            "control_tower_payment_reconciliation_payment_intent_id": payment_intent_id,
            "control_tower_payment_reconciliation_payment_status": payment_status,
            "control_tower_payment_reconciliation_amount_received_cents": received_amount_cents,
            "control_tower_payment_reconciliation_expected_amount_cents": expected_amount_cents,
            "control_tower_payment_reconciliation_requires_staff_approval": True,
            "control_tower_payment_local_posted": False,
            "stripe_payment_received": outcome == "success",
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
        }
    )
    reservation.price_breakdown = breakdown
    reservation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reservation)

    await _record_crog_vrs_payment_reconciliation_audit(
        db=db,
        reservation=reservation,
        metadata=metadata,
        session=session,
        outcome=outcome,
        detail=detail,
        expected_amount_cents=expected_amount_cents,
        received_amount_cents=received_amount_cents,
    )
    logger.info(
        "crog_vrs_reservation_payment_staged",
        reservation_id=str(reservation.id),
        checkout_session_id=session_id,
        payment_intent_id=payment_intent_id,
        outcome=outcome,
        state=reconciliation_state,
    )
    return True


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


async def _process_invoice_paid(
    invoice_obj: dict,
    db: AsyncSession,
) -> None:
    """
    Handle ``invoice.paid`` — clear the Accounts Receivable trust entry
    for a FinancialApproval invoice and stamp an immutable audit trail.

    Idempotent: skips if the approval is not in ``approved`` status or
    if the ``context_payload`` already contains a ``payment_cleared_at``
    timestamp.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from backend.models.financial_approval import FinancialApproval
    from backend.services.trust_ledger import post_invoice_clearing_entry

    stripe_invoice_id = str(invoice_obj.get("id", "")).strip()
    if not stripe_invoice_id:
        return

    metadata = invoice_obj.get("metadata") or {}
    source = metadata.get("source", "")
    if source != "financial_approval_invoice":
        return

    try:
        result = await db.execute(
            select(FinancialApproval).where(
                FinancialApproval.stripe_invoice_id == stripe_invoice_id,
            )
        )
        approval = result.scalars().first()

        if approval is None:
            approval_id_from_meta = metadata.get("approval_id", "")
            if approval_id_from_meta:
                from uuid import UUID

                result = await db.execute(
                    select(FinancialApproval).where(
                        FinancialApproval.id == UUID(approval_id_from_meta),
                    )
                )
                approval = result.scalars().first()

        if approval is None:
            logger.warning(
                "invoice_paid_approval_not_found",
                stripe_invoice_id=stripe_invoice_id,
                metadata=metadata,
            )
            return

        existing_ctx = approval.context_payload or {}
        if existing_ctx.get("payment_cleared_at"):
            logger.info(
                "invoice_paid_already_cleared",
                stripe_invoice_id=stripe_invoice_id,
                approval_id=str(approval.id),
            )
            return

        amount_paid_cents = int(invoice_obj.get("amount_paid", 0))
        if amount_paid_cents <= 0:
            logger.warning(
                "invoice_paid_zero_amount",
                stripe_invoice_id=stripe_invoice_id,
                approval_id=str(approval.id),
            )
            return

        await post_invoice_clearing_entry(
            db,
            amount_cents=amount_paid_cents,
            stripe_invoice_id=stripe_invoice_id,
        )

        now = datetime.now(timezone.utc)
        receipt_url = str(
            invoice_obj.get("hosted_invoice_url")
            or invoice_obj.get("invoice_pdf")
            or ""
        )
        charge_id = ""
        charge_obj = invoice_obj.get("charge")
        if isinstance(charge_obj, str):
            charge_id = charge_obj
        elif isinstance(charge_obj, dict):
            charge_id = charge_obj.get("id", "")

        updated_ctx = {
            **existing_ctx,
            "payment_cleared_at": now.isoformat(),
            "payment_amount_cents": amount_paid_cents,
            "stripe_receipt_url": receipt_url,
            "stripe_charge_id": charge_id,
            "stripe_invoice_status": str(invoice_obj.get("status", "")),
            "cleared_by": "stripe_invoice_paid_webhook",
        }
        approval.context_payload = updated_ctx

        await db.commit()

        logger.info(
            "invoice_paid_ledger_cleared",
            approval_id=str(approval.id),
            stripe_invoice_id=stripe_invoice_id,
            amount_paid_cents=amount_paid_cents,
            reservation_id=approval.reservation_id,
            receipt_url=receipt_url,
        )

    except Exception as exc:
        await db.rollback()
        logger.error(
            "invoice_paid_processing_failed",
            stripe_invoice_id=stripe_invoice_id,
            error=str(exc)[:400],
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


# ---------------------------------------------------------------------------
# Storefront Checkout → Reservation + Streamline Write-Back
# ---------------------------------------------------------------------------


async def _process_storefront_settlement(
    payment_object: dict,
    metadata: dict,
    db: AsyncSession,
) -> None:
    """
    Handle payment_intent.succeeded for storefront_checkout source.

    1. Find-or-create the Guest record
    2. Create a confirmed Reservation via ReservationEngine
    3. Optionally bridge to Streamline if settlement bridge is enabled
    """
    from datetime import date as date_type
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy import select

    from backend.models.guest import Guest
    from backend.services.reservation_engine import ReservationEngine

    payment_intent_id = str(payment_object.get("id", "")).strip()
    amount_cents = int(payment_object.get("amount_received") or payment_object.get("amount", 0))
    guest_email = metadata.get("guest_email", "").strip()
    guest_name = metadata.get("guest_name", "").strip()
    phone = metadata.get("phone", "").strip()
    property_id_str = metadata.get("property_id", "").strip()
    arrival_str = metadata.get("arrival", "")
    departure_str = metadata.get("departure", "")
    adults = int(metadata.get("adults", 2))
    children = int(metadata.get("children", 0))
    pets = int(metadata.get("pets", 0))

    if not property_id_str or not arrival_str or not departure_str:
        logger.warning(
            "storefront_settlement_missing_metadata",
            payment_intent_id=payment_intent_id,
            metadata=metadata,
        )
        return

    property_id = UUID(property_id_str)
    check_in = date_type.fromisoformat(arrival_str)
    check_out = date_type.fromisoformat(departure_str)

    existing = await db.execute(
        text(
            "SELECT id FROM reservations "
            "WHERE price_breakdown->>'stripe_payment_intent_id' = :pi "
            "LIMIT 1"
        ),
        {"pi": payment_intent_id},
    )
    if existing.scalar() is not None:
        logger.info(
            "storefront_settlement_already_processed",
            payment_intent_id=payment_intent_id,
        )
        return

    guest_result = await db.execute(
        select(Guest).where(Guest.email == guest_email).limit(1)
    )
    guest = guest_result.scalars().first()

    if guest is None:
        name_parts = guest_name.split(" ", 1)
        guest = Guest(
            first_name=name_parts[0] if name_parts else "Guest",
            last_name=name_parts[1] if len(name_parts) > 1 else "",
            email=guest_email or f"storefront-{payment_intent_id[:8]}@placeholder.local",
            phone_number=phone or "0000000000",
        )
        db.add(guest)
        await db.flush()
        logger.info(
            "storefront_guest_created",
            guest_id=str(guest.id),
            email=guest_email,
        )

    total_amount = Decimal(str(amount_cents)) / Decimal("100")

    engine = ReservationEngine()
    try:
        reservation = await engine.create_reservation(
            db,
            data={
                "guest_id": guest.id,
                "property_id": property_id,
                "check_in_date": check_in,
                "check_out_date": check_out,
                "num_guests": adults + children,
                "num_adults": adults,
                "num_children": children,
                "num_pets": pets,
                "booking_source": "storefront_checkout",
                "total_amount": total_amount,
                "paid_amount": total_amount,
                "balance_due": Decimal("0.00"),
                "currency": "USD",
                "internal_notes": f"Stripe PI: {payment_intent_id}",
            },
        )
    except ValueError as exc:
        logger.error(
            "storefront_reservation_creation_failed",
            payment_intent_id=payment_intent_id,
            error=str(exc),
        )
        return

    reservation.guest_email = guest_email
    reservation.guest_name = guest_name
    reservation.guest_phone = phone
    reservation.price_breakdown = {
        "stripe_payment_intent_id": payment_intent_id,
        "amount_cents": amount_cents,
        "source": "storefront_checkout",
    }

    from backend.api.storefront_checkout import retrieve_ledger_line_items, retrieve_tax_snapshot

    tax_snap = await retrieve_tax_snapshot(payment_intent_id)
    if tax_snap:
        reservation.tax_breakdown = tax_snap
        logger.info(
            "tax_breakdown_persisted",
            reservation_id=str(reservation.id),
            payment_intent_id=payment_intent_id,
        )

    cached_items = await retrieve_ledger_line_items(payment_intent_id)
    if cached_items:
        reservation.price_breakdown = {
            "stripe_payment_intent_id": payment_intent_id,
            "amount_cents": amount_cents,
            "source": "storefront_checkout",
            "line_items": cached_items,
        }
        logger.info(
            "ledger_line_items_persisted",
            reservation_id=str(reservation.id),
            item_count=len(cached_items),
        )

    reservation.security_deposit_required = pets > 0
    if pets > 0:
        reservation.security_deposit_amount = Decimal("250.00")
        reservation.security_deposit_status = "pending"

    from backend.services.trust_ledger import post_checkout_trust_entry

    try:
        await post_checkout_trust_entry(
            db,
            reservation_id=str(reservation.id),
            amount_cents=amount_cents,
            stripe_pi_id=payment_intent_id,
        )
        logger.info(
            "trust_ledger_entry_posted",
            reservation_id=str(reservation.id),
            amount_cents=amount_cents,
        )
    except Exception as exc:
        logger.warning(
            "trust_ledger_entry_failed",
            reservation_id=str(reservation.id),
            error=str(exc)[:300],
        )

    await db.commit()

    logger.info(
        "storefront_reservation_confirmed",
        payment_intent_id=payment_intent_id,
        reservation_id=str(reservation.id),
        confirmation_code=reservation.confirmation_code,
        property_id=str(property_id),
        total_amount=float(total_amount),
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
                "storefront_legacy_sync_attempt",
                reservation_id=str(reservation.id),
                legacy_notified=bridge.legacy_notified,
                detail=bridge.detail,
            )
        except Exception as exc:
            logger.warning(
                "storefront_legacy_sync_deferred",
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
                    "storefront_settlement_replay_queued",
                    deferred_api_write_id=qid,
                    reservation_id=str(reservation.id),
                )

            from backend.models.pending_sync import PendingSync
            pending = PendingSync(
                reservation_id=reservation.id,
                property_id=property_id,
                sync_type="create_reservation",
                status="pending",
                payload={
                    "confirmation_code": reservation.confirmation_code,
                    "stripe_payment_intent_id": payment_intent_id,
                    "guest_email": guest_email,
                    "check_in": str(check_in),
                    "check_out": str(check_out),
                    "amount_cents": amount_cents,
                },
            )
            db.add(pending)
            await db.commit()
            logger.info(
                "hermes_pending_sync_buffered",
                reservation_id=str(reservation.id),
            )
