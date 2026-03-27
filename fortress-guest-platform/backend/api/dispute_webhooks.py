"""
Stripe Dispute Webhooks — Chargeback Ironclad.

Handles Stripe dispute lifecycle events and autonomously compiles
evidence packets from signed rental agreements + IoT lock logs:

  charge.dispute.created   -> lookup reservation, compile evidence, submit to Stripe
  charge.dispute.updated   -> track status changes (under_review, won, lost)
  charge.dispute.closed    -> final status recording
"""

import stripe
import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Header, HTTPException, Request, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.models import Reservation, RentalAgreement
from backend.services.async_jobs import enqueue_async_job

logger = structlog.get_logger(service="dispute_webhooks")
router = APIRouter()


def _verify_dispute_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature for dispute events."""
    secret = settings.stripe_dispute_webhook_secret or settings.stripe_webhook_secret
    if not secret:
        raise ValueError("No Stripe dispute webhook secret configured")
    return stripe.Webhook.construct_event(payload, sig_header, secret)


async def _lookup_reservation_by_payment(
    db: AsyncSession, payment_intent_id: str
) -> Reservation | None:
    """Find the reservation linked to a Stripe payment_intent."""
    result = await db.execute(
        text("""
            SELECT id FROM reservations
            WHERE stripe_payment_intent = :pi
               OR payment_metadata->>'payment_intent_id' = :pi
            LIMIT 1
        """),
        {"pi": payment_intent_id},
    )
    row = result.first()
    if not row:
        return None
    return await db.get(Reservation, row.id)


async def _find_signed_agreement(
    db: AsyncSession, reservation_id, property_id
) -> RentalAgreement | None:
    """Find the most recent signed rental agreement for a reservation."""
    query = (
        select(RentalAgreement)
        .where(RentalAgreement.status == "signed")
        .order_by(RentalAgreement.signed_at.desc())
        .limit(1)
    )
    if reservation_id:
        query = query.where(RentalAgreement.reservation_id == reservation_id)
    elif property_id:
        query = query.where(RentalAgreement.property_id == property_id)
    else:
        return None

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _fetch_iot_lock_events(db: AsyncSession, property_id, check_in, check_out) -> list:
    """Query IoT lock access logs for the reservation's date range."""
    try:
        result = await db.execute(
            text("""
                SELECT event_type, device_id, timestamp, user_code, metadata
                FROM iot_event_log
                WHERE property_id = :pid
                  AND timestamp BETWEEN :ci AND :co
                  AND event_type IN ('lock', 'unlock', 'code_set', 'code_used')
                ORDER BY timestamp ASC
            """),
            {"pid": str(property_id), "ci": check_in, "co": check_out},
        )
        rows = result.all()
        return [
            {
                "event_type": r.event_type,
                "device_id": r.device_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "user_code": r.user_code,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("iot_event_query_failed", error=str(e)[:200])
        return []


async def _create_dispute_record(db: AsyncSession, dispute: dict, reservation, agreement, iot_events):
    """Insert initial dispute_evidence row."""
    obj = dispute.get("data", {}).get("object", {})
    dispute_id = obj.get("id", "")
    amount = (obj.get("amount") or 0) / 100.0
    reason = obj.get("reason", "")
    payment_intent = obj.get("payment_intent", "")

    await db.execute(
        text("""
            INSERT INTO dispute_evidence
                (dispute_id, payment_intent, reservation_id, guest_id, property_id,
                 rental_agreement_id, iot_events_count, dispute_amount, dispute_reason,
                 dispute_status, status)
            VALUES (:did, :pi, :rid, :gid, :pid, :raid, :iot_count, :amount, :reason,
                    :dstatus, 'pending')
            ON CONFLICT (dispute_id) DO UPDATE SET
                dispute_status = :dstatus,
                dispute_amount = :amount,
                updated_at = NOW()
        """),
        {
            "did": dispute_id,
            "pi": payment_intent,
            "rid": str(reservation.id) if reservation else None,
            "gid": str(reservation.guest_id) if reservation and reservation.guest_id else None,
            "pid": str(reservation.property_id) if reservation and reservation.property_id else None,
            "raid": str(agreement.id) if agreement else None,
            "iot_count": len(iot_events),
            "amount": amount,
            "reason": reason,
            "dstatus": obj.get("status", "needs_response"),
        },
    )
    await db.commit()
    return dispute_id


async def _handle_dispute_created(
    event: dict,
    db: AsyncSession,
    request: Request,
    arq_redis: ArqRedis,
):
    """Process charge.dispute.created — lookup evidence and compile packet."""
    obj = event.get("data", {}).get("object", {})
    dispute_id = obj.get("id", "")
    payment_intent = obj.get("payment_intent", "")
    amount_cents = obj.get("amount", 0)
    reason = obj.get("reason", "")

    logger.info(
        "dispute_created",
        dispute_id=dispute_id,
        payment_intent=payment_intent,
        amount=amount_cents / 100.0,
        reason=reason,
    )

    reservation = await _lookup_reservation_by_payment(db, payment_intent)
    if not reservation:
        logger.warning("dispute_no_reservation", dispute_id=dispute_id, payment_intent=payment_intent)
        await _create_dispute_record(db, event, None, None, [])
        return

    agreement = await _find_signed_agreement(db, reservation.id, reservation.property_id)

    iot_events = []
    if reservation.property_id and reservation.check_in_date and reservation.check_out_date:
        iot_events = await _fetch_iot_lock_events(
            db, reservation.property_id,
            reservation.check_in_date, reservation.check_out_date,
        )

    await _create_dispute_record(db, event, reservation, agreement, iot_events)

    dispute_job = await enqueue_async_job(
        db,
        worker_name="run_dispute_evidence_job",
        job_name="run_dispute_evidence",
        payload={
            "dispute_id": dispute_id,
            "reservation_id": str(reservation.id),
        },
        requested_by="stripe_webhook",
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )

    logger.info(
        "dispute_evidence_compilation_queued",
        dispute_id=dispute_id,
        reservation_id=str(reservation.id),
        job_id=str(dispute_job.id),
        has_agreement=bool(agreement),
        iot_events=len(iot_events),
    )


async def _handle_dispute_status_update(event: dict, db: AsyncSession):
    """Update dispute_evidence status on dispute.updated / dispute.closed."""
    obj = event.get("data", {}).get("object", {})
    dispute_id = obj.get("id", "")
    new_status = obj.get("status", "")

    status_map = {
        "won": "won",
        "lost": "lost",
        "under_review": "submitted",
        "warning_closed": "expired",
        "needs_response": "pending",
    }
    mapped = status_map.get(new_status, new_status)

    await db.execute(
        text("""
            UPDATE dispute_evidence
            SET dispute_status = :dstatus, status = :status, updated_at = NOW()
            WHERE dispute_id = :did
        """),
        {"did": dispute_id, "dstatus": new_status, "status": mapped},
    )
    await db.commit()

    logger.info("dispute_status_updated", dispute_id=dispute_id, new_status=new_status)


@router.post("/stripe-disputes")
async def handle_stripe_dispute_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    """
    Receive and process Stripe dispute webhook events.
    Handles: charge.dispute.created, charge.dispute.updated, charge.dispute.closed
    """
    payload = await request.body()

    try:
        event = _verify_dispute_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError:
        logger.warning("dispute_webhook_sig_invalid")
        raise HTTPException(400, "Invalid signature")
    except ValueError as e:
        logger.error("dispute_webhook_config_error", error=str(e))
        raise HTTPException(500, "Webhook configuration error")

    event_type = event.get("type", "")
    logger.info("dispute_webhook_received", event_type=event_type)

    if event_type == "charge.dispute.created":
        await _handle_dispute_created(event, db, request, arq_redis)
    elif event_type in ("charge.dispute.updated", "charge.dispute.closed"):
        await _handle_dispute_status_update(event, db)
    else:
        logger.info("dispute_webhook_unhandled", event_type=event_type)

    return {"received": True}
