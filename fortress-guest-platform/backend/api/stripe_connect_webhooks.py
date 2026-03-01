"""
Stripe Connect Webhooks — Payout Lifecycle Tracking.

Receives webhook events from Stripe Connect to track the full lifecycle
of owner payouts from Transfer creation through ACH settlement:

  transfer.paid      -> payout_ledger status = 'completed', journal liability clearing
  transfer.failed    -> payout_ledger status = 'failed', log failure reason
  payout.paid        -> payout_ledger status = 'settled' (funds in owner's bank)
  payout.failed      -> payout_ledger status = 'failed', alert
  account.updated    -> owner_payout_accounts status sync (onboarding completion)

Every inbound event is logged to stripe_connect_events for auditability.
"""

import stripe
import structlog
from fastapi import APIRouter, Header, HTTPException, Request, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db

logger = structlog.get_logger(service="stripe_connect_webhooks")
router = APIRouter()


def _verify_event(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and construct the event object."""
    secret = settings.stripe_connect_webhook_secret or settings.stripe_webhook_secret
    if not secret:
        raise ValueError("No Stripe Connect webhook secret configured")
    return stripe.Webhook.construct_event(payload, sig_header, secret)


async def _log_event(db: AsyncSession, event: dict):
    """Persist every inbound Stripe event for audit trail."""
    event_id = event.get("id", "")
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    await db.execute(
        text("""
            INSERT INTO stripe_connect_events
                (stripe_event_id, event_type, account_id, transfer_id, payout_id,
                 amount, status, failure_code, failure_message, raw_payload)
            VALUES (:eid, :etype, :acct, :xfer, :payout, :amount, :status,
                    :fcode, :fmsg, :raw::jsonb)
            ON CONFLICT (stripe_event_id) DO NOTHING
        """),
        {
            "eid": event_id,
            "etype": event_type,
            "acct": obj.get("destination") or obj.get("id", ""),
            "xfer": obj.get("id") if "transfer" in event_type else None,
            "payout": obj.get("id") if "payout" in event_type else None,
            "amount": (obj.get("amount") or 0) / 100.0 if obj.get("amount") else None,
            "status": obj.get("status"),
            "fcode": obj.get("failure_code"),
            "fmsg": obj.get("failure_message"),
            "raw": str(event).replace("'", '"')[:10000],
        },
    )


async def _handle_transfer_paid(obj: dict, db: AsyncSession):
    """Transfer from platform to connected account succeeded.

    Advance payout_ledger from 'processing' -> 'completed' and write the
    liability-clearing journal entry (DR 2000 Owner Payable, CR 1010 Cash).
    """
    transfer_id = obj.get("id", "")
    amount_cents = obj.get("amount", 0)
    amount = amount_cents / 100.0

    result = await db.execute(
        text("""
            UPDATE payout_ledger
            SET status = 'completed',
                stripe_transfer_id = :xfer_id,
                completed_at = NOW()
            WHERE stripe_transfer_id = :xfer_id
              AND status = 'processing'
            RETURNING id, property_id, confirmation_code, owner_amount
        """),
        {"xfer_id": transfer_id},
    )
    row = result.first()
    if not row:
        logger.info("transfer_paid_no_match", transfer_id=transfer_id)
        return

    je_result = await db.execute(
        text("""
            INSERT INTO journal_entries
                (description, reference_type, reference_id, property_id,
                 posted_by, source_system)
            VALUES (:desc, 'owner_payout_settled', :ref, :pid,
                    'stripe_connect_webhook', 'stripe_connect')
            RETURNING id
        """),
        {
            "desc": f"Payout Settled: {row.confirmation_code} | Transfer {transfer_id}",
            "ref": row.confirmation_code,
            "pid": row.property_id,
        },
    )
    je_id = je_result.scalar()

    await db.execute(
        text("""
            INSERT INTO journal_line_items
                (journal_entry_id, account_id, debit, credit)
            VALUES
                (:je, (SELECT id FROM accounts WHERE code = '2000'), :amt, 0),
                (:je, (SELECT id FROM accounts WHERE code = '1010'), 0, :amt)
        """),
        {"je": je_id, "amt": float(row.owner_amount)},
    )

    logger.info(
        "transfer_paid_settled",
        transfer_id=transfer_id,
        payout_ledger_id=row.id,
        confirmation_code=row.confirmation_code,
        amount=amount,
        journal_entry_id=je_id,
    )


async def _handle_transfer_failed(obj: dict, db: AsyncSession):
    """Transfer from platform to connected account failed."""
    transfer_id = obj.get("id", "")
    failure_code = obj.get("failure_code", "unknown")
    failure_message = obj.get("failure_message", "")

    result = await db.execute(
        text("""
            UPDATE payout_ledger
            SET status = 'failed',
                failure_reason = :reason
            WHERE stripe_transfer_id = :xfer_id
              AND status = 'processing'
            RETURNING id, confirmation_code, owner_amount
        """),
        {"xfer_id": transfer_id, "reason": f"{failure_code}: {failure_message}"},
    )
    row = result.first()
    logger.error(
        "transfer_failed",
        transfer_id=transfer_id,
        failure_code=failure_code,
        failure_message=failure_message,
        payout_ledger_id=row.id if row else None,
    )


async def _handle_payout_paid(obj: dict, db: AsyncSession):
    """ACH deposit to owner's bank account succeeded (funds landed)."""
    payout_id = obj.get("id", "")
    destination_acct = obj.get("destination", "")

    await db.execute(
        text("""
            UPDATE payout_ledger
            SET status = 'settled',
                stripe_payout_id = :payout_id
            WHERE status = 'completed'
              AND property_id IN (
                  SELECT property_id FROM owner_payout_accounts
                  WHERE stripe_account_id = :acct
              )
              AND stripe_payout_id IS NULL
        """),
        {"payout_id": payout_id, "acct": destination_acct},
    )

    logger.info(
        "payout_paid_ach_settled",
        payout_id=payout_id,
        destination_account=destination_acct[:12] + "...",
    )


async def _handle_payout_failed(obj: dict, db: AsyncSession):
    """ACH deposit to owner's bank account failed."""
    payout_id = obj.get("id", "")
    failure_code = obj.get("failure_code", "unknown")
    failure_message = obj.get("failure_message", "")
    destination_acct = obj.get("destination", "")

    await db.execute(
        text("""
            UPDATE payout_ledger
            SET status = 'failed',
                failure_reason = :reason
            WHERE status IN ('completed', 'settled')
              AND property_id IN (
                  SELECT property_id FROM owner_payout_accounts
                  WHERE stripe_account_id = :acct
              )
              AND stripe_payout_id IS NULL
        """),
        {
            "reason": f"ACH failed: {failure_code}: {failure_message}",
            "acct": destination_acct,
        },
    )

    logger.error(
        "payout_failed_ach",
        payout_id=payout_id,
        failure_code=failure_code,
        failure_message=failure_message,
    )


async def _handle_account_updated(obj: dict, db: AsyncSession):
    """Connected account status changed (e.g., owner completed onboarding)."""
    account_id = obj.get("id", "")
    charges_enabled = obj.get("charges_enabled", False)
    payouts_enabled = obj.get("payouts_enabled", False)
    details_submitted = obj.get("details_submitted", False)

    if charges_enabled and payouts_enabled:
        new_status = "active"
    elif details_submitted:
        new_status = "restricted"
    else:
        new_status = "onboarding"

    result = await db.execute(
        text("""
            UPDATE owner_payout_accounts
            SET account_status = :status,
                updated_at = NOW()
            WHERE stripe_account_id = :acct_id
              AND account_status != :status
            RETURNING property_id, owner_name
        """),
        {"status": new_status, "acct_id": account_id},
    )
    row = result.first()
    if row:
        logger.info(
            "connect_account_status_updated",
            stripe_account=account_id[:12] + "...",
            new_status=new_status,
            property_id=row.property_id,
            owner=row.owner_name,
        )


_HANDLERS = {
    "transfer.paid": _handle_transfer_paid,
    "transfer.failed": _handle_transfer_failed,
    "payout.paid": _handle_payout_paid,
    "payout.failed": _handle_payout_failed,
    "account.updated": _handle_account_updated,
}


@router.post("/stripe-connect")
async def stripe_connect_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """Receive and dispatch Stripe Connect webhook events."""
    payload = await request.body()

    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    try:
        event = _verify_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError:
        logger.error("stripe_connect_webhook_signature_invalid")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.error("stripe_connect_webhook_verify_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    event_type = event.get("type", "")
    event_id = event.get("id", "")

    logger.info("stripe_connect_webhook_received", event_type=event_type, event_id=event_id)

    await _log_event(db, event)

    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            obj = event["data"]["object"]
            await handler(obj, db)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "stripe_connect_webhook_handler_failed",
                event_type=event_type,
                event_id=event_id,
                error=str(exc),
            )
            raise HTTPException(status_code=500, detail="Webhook processing failed")
    else:
        logger.debug("stripe_connect_webhook_unhandled", event_type=event_type)
        await db.commit()

    return {"status": "ok", "event_type": event_type}
