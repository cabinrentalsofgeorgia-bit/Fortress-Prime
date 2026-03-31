"""
Email Bridge API — Routes emails classified as CABIN_VRS from the
Email Intake Command into the guest platform.

When the email classifier tags an email as CABIN_VRS, the master console
POSTs here.  We:
  1. Find or create a guest profile from the sender
  2. Link to any active reservation
  3. Store the email as a message record
  4. Optionally run the orchestrator to draft a response
"""
from datetime import date, datetime
import hashlib
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.database import get_db
from backend.core.security_swarm import verify_swarm_token
from backend.models import Guest, Reservation, Message

router = APIRouter()
logger = structlog.get_logger()


class CabinEmailPayload(BaseModel):
    """Payload from the Email Intake system."""
    sender_email: str
    sender_name: Optional[str] = None
    sender_phone: Optional[str] = None
    subject: str
    body: str
    email_id: Optional[int] = None
    priority: Optional[str] = "P2"
    division_confidence: Optional[float] = 0.0


def _bridge_phone(sender_email: str, sender_phone: Optional[str]) -> str:
    phone = (sender_phone or "").strip()
    if phone:
        return phone
    digest = hashlib.sha256((sender_email or "").strip().lower().encode("utf-8")).hexdigest()
    digits = "".join(str(int(ch, 16) % 10) for ch in digest[:10])
    return f"+1999{digits}"


@router.post("/ingest")
async def ingest_cabin_email(
    payload: CabinEmailPayload,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
):
    """
    Receive a CABIN_VRS-classified email and integrate it into the
    guest platform as a message + guest record.
    """
    log = logger.bind(endpoint="email_bridge", sender=payload.sender_email)
    log.info("cabin_email_received", subject=payload.subject[:60])

    # ── 1. Find or create guest ──
    guest = None

    bridge_phone = _bridge_phone(payload.sender_email, payload.sender_phone)

    if payload.sender_phone:
        result = await db.execute(
            select(Guest).where(Guest.phone_number == payload.sender_phone)
        )
        guest = result.scalar_one_or_none()

    if not guest:
        result = await db.execute(
            select(Guest).where(Guest.email == payload.sender_email)
        )
        guest = result.scalar_one_or_none()

    if not guest:
        name_parts = (payload.sender_name or "").split(None, 1)
        guest_id = (
            await db.execute(
                text("""
                    INSERT INTO guests (
                        id,
                        email,
                        first_name,
                        last_name,
                        phone,
                        guest_source,
                        verification_status,
                        loyalty_tier,
                        language_preference,
                        preferred_contact_method,
                        opt_in_marketing,
                        opt_in_sms,
                        opt_in_email,
                        timezone,
                        total_stays,
                        lifetime_stays,
                        lifetime_nights,
                        lifetime_revenue,
                        value_score,
                        risk_score,
                        preferences,
                        is_vip,
                        is_blacklisted,
                        requires_supervision,
                        is_do_not_contact,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :email,
                        :first_name,
                        :last_name,
                        :phone,
                        'email_intake',
                        'unverified',
                        'bronze',
                        'en',
                        'sms',
                        TRUE,
                        TRUE,
                        TRUE,
                        'America/New_York',
                        0,
                        0,
                        0,
                        0,
                        50,
                        10,
                        CAST(:preferences AS jsonb),
                        FALSE,
                        FALSE,
                        FALSE,
                        FALSE,
                        NOW(),
                        NOW()
                    )
                    RETURNING id
                """),
                {
                    "id": str(uuid4()),
                    "email": payload.sender_email,
                    "first_name": name_parts[0] if name_parts else None,
                    "last_name": name_parts[1] if len(name_parts) > 1 else None,
                    "phone": bridge_phone,
                    "preferences": "{}",
                },
            )
        ).scalar_one()
        guest = await db.get(Guest, guest_id)
        log.info("guest_created_from_email", guest_id=str(guest.id))

    # ── 2. Link to active reservation ──
    reservation = None
    if guest.id:
        today = date.today()
        res_q = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.guest_id == guest.id,
                    Reservation.check_out_date >= today,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                )
            ).order_by(Reservation.check_in_date.asc()).limit(1)
        )
        reservation = res_q.scalar_one_or_none()

    # ── 3. Store as a message ──
    message = Message(
        external_id=f"email-{payload.email_id or uuid4().hex[:8]}",
        direction="inbound",
        phone_from=payload.sender_phone or bridge_phone,
        phone_to="email-bridge",
        body=f"[Email From: {payload.sender_email}]\n[{payload.subject}]\n\n{payload.body}",
        status="received",
        sent_at=datetime.utcnow(),
        guest_id=guest.id,
        reservation_id=reservation.id if reservation else None,
        intent="email_cabin_vrs",
        category="email_bridge",
        requires_human_review=True,
        provider="email",
        trace_id=uuid4(),
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    log.info(
        "cabin_email_ingested",
        message_id=str(message.id),
        guest_id=str(guest.id),
        has_reservation=reservation is not None,
    )

    return {
        "ok": True,
        "message_id": str(message.id),
        "guest_id": str(guest.id),
        "guest_name": guest.full_name,
        "reservation_id": str(reservation.id) if reservation else None,
    }
