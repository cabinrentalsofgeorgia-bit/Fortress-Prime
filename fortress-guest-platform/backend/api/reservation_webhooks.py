"""
Reservation Webhooks — Real-Time Booking Intake Engine

Exposes POST /api/webhooks/reservations for zero-latency reservation ingestion.
When a guest books via the direct site, Streamline, or an OTA, the payload
hits this endpoint, validates via HMAC-SHA256, upserts the reservation, and
publishes to trust.revenue.staged for instant ledger journaling.

The Revenue Consumer Daemon picks up the event within milliseconds and
executes the CROG Alpha 65/35 split — all before the guest receives their
confirmation email.

Security: HMAC-SHA256 signature via X-Fortress-Signature header.
Auth: Public endpoint (no JWT); protected by shared secret.
"""

import hmac
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.event_publisher import EventPublisher

logger = structlog.get_logger(service="reservation_webhooks")
router = APIRouter()


class BookingEventType(str, Enum):
    booking_created = "booking_created"
    booking_updated = "booking_updated"
    booking_cancelled = "booking_cancelled"


class ReservationWebhookPayload(BaseModel):
    property_id: str = Field(..., min_length=1, max_length=100)
    confirmation_code: str = Field(..., min_length=1, max_length=100)
    event_type: BookingEventType
    total_amount: Decimal = Field(default=Decimal("0"), ge=0)
    cleaning_fee: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    nightly_rate: Decimal = Field(default=Decimal("0"), ge=0)
    nights_count: int = Field(default=0, ge=0)
    check_in_date: date
    check_out_date: date
    guest_name: Optional[str] = Field(default=None, max_length=255)
    guest_email: Optional[str] = Field(default=None, max_length=255)
    guest_phone: Optional[str] = Field(default=None, max_length=50)
    booking_source: str = Field(default="direct", max_length=50)
    paid_amount: Decimal = Field(default=Decimal("0"), ge=0)
    num_guests: int = Field(default=1, ge=1)

    @field_validator("check_out_date")
    @classmethod
    def checkout_after_checkin(cls, v, info):
        if "check_in_date" in info.data and v <= info.data["check_in_date"]:
            raise ValueError("check_out_date must be after check_in_date")
        return v

    @field_validator("guest_phone")
    @classmethod
    def normalize_phone(cls, v):
        if v is None:
            return v
        import re
        digits = re.sub(r"[^\d+]", "", v)
        if digits and not digits.startswith("+"):
            if len(digits) == 10:
                digits = f"+1{digits}"
            elif len(digits) == 11 and digits.startswith("1"):
                digits = f"+{digits}"
        return digits or v


def _verify_hmac(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature against the raw request body."""
    if not secret:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _already_journaled(db: AsyncSession, confirmation_code: str) -> bool:
    """Check if this reservation's revenue has already been journaled."""
    result = await db.execute(
        text("""
            SELECT 1 FROM journal_entries
            WHERE reference_id = :code
              AND reference_type = 'reservation_revenue'
            LIMIT 1
        """),
        {"code": confirmation_code},
    )
    return result.first() is not None


async def _upsert_reservation(
    db: AsyncSession, payload: ReservationWebhookPayload
) -> str:
    """Upsert reservation into the reservations table. Returns 'created' or 'updated'."""
    existing = await db.execute(
        text("SELECT id, status FROM reservations WHERE confirmation_code = :code LIMIT 1"),
        {"code": payload.confirmation_code},
    )
    row = existing.first()

    status_map = {
        BookingEventType.booking_created: "confirmed",
        BookingEventType.booking_updated: "confirmed",
        BookingEventType.booking_cancelled: "cancelled",
    }
    res_status = status_map[payload.event_type]

    if row:
        await db.execute(
            text("""
                UPDATE reservations SET
                    check_in_date = :cin, check_out_date = :cout,
                    total_amount = :total, cleaning_fee = :clean,
                    tax_amount = :tax, nightly_rate = :rate,
                    nights_count = :nights, paid_amount = :paid,
                    num_guests = :guests, status = :status,
                    booking_source = :source, updated_at = :now
                WHERE confirmation_code = :code
            """),
            {
                "cin": payload.check_in_date, "cout": payload.check_out_date,
                "total": float(payload.total_amount),
                "clean": float(payload.cleaning_fee),
                "tax": float(payload.tax_amount),
                "rate": float(payload.nightly_rate),
                "nights": payload.nights_count,
                "paid": float(payload.paid_amount),
                "guests": payload.num_guests,
                "status": res_status,
                "source": payload.booking_source,
                "now": datetime.now(timezone.utc),
                "code": payload.confirmation_code,
            },
        )
        return "updated"
    else:
        res_id = str(uuid.uuid4())
        prop_result = await db.execute(
            text("SELECT id FROM properties WHERE streamline_property_id = :pid OR id::text = :pid LIMIT 1"),
            {"pid": payload.property_id},
        )
        prop_row = prop_result.first()
        prop_uuid = str(prop_row.id) if prop_row else None

        guest_id = None
        if payload.guest_email:
            guest_id = await _upsert_guest(db, payload)

        await db.execute(
            text("""
                INSERT INTO reservations
                    (id, confirmation_code, property_id, guest_id,
                     check_in_date, check_out_date, total_amount,
                     cleaning_fee, tax_amount, nightly_rate, nights_count,
                     paid_amount, num_guests, status, booking_source,
                     created_at, updated_at)
                VALUES
                    (:id, :code, :pid, :gid,
                     :cin, :cout, :total,
                     :clean, :tax, :rate, :nights,
                     :paid, :guests, :status, :source,
                     :now, :now)
            """),
            {
                "id": res_id, "code": payload.confirmation_code,
                "pid": prop_uuid, "gid": guest_id,
                "cin": payload.check_in_date, "cout": payload.check_out_date,
                "total": float(payload.total_amount),
                "clean": float(payload.cleaning_fee),
                "tax": float(payload.tax_amount),
                "rate": float(payload.nightly_rate),
                "nights": payload.nights_count,
                "paid": float(payload.paid_amount),
                "guests": payload.num_guests,
                "status": res_status,
                "source": payload.booking_source,
                "now": datetime.now(timezone.utc),
            },
        )
        return "created"


async def _upsert_guest(
    db: AsyncSession, payload: ReservationWebhookPayload
) -> Optional[str]:
    """Create or update guest record from webhook data."""
    if not payload.guest_email:
        return None

    existing = await db.execute(
        text("SELECT id FROM guests WHERE email = :email LIMIT 1"),
        {"email": payload.guest_email},
    )
    row = existing.first()
    if row:
        if payload.guest_name or payload.guest_phone:
            updates = []
            params: dict = {"email": payload.guest_email}
            if payload.guest_name:
                updates.append("name = :name")
                params["name"] = payload.guest_name
            if payload.guest_phone:
                updates.append("phone = :phone")
                params["phone"] = payload.guest_phone
            if updates:
                await db.execute(
                    text(f"UPDATE guests SET {', '.join(updates)}, updated_at = NOW() WHERE email = :email"),
                    params,
                )
        return str(row.id)

    guest_id = str(uuid.uuid4())
    name_parts = (payload.guest_name or "Guest").split(" ", 1)
    await db.execute(
        text("""
            INSERT INTO guests (id, email, name, first_name, last_name, phone, created_at)
            VALUES (:id, :email, :name, :first, :last, :phone, NOW())
        """),
        {
            "id": guest_id,
            "email": payload.guest_email,
            "name": payload.guest_name or "Guest",
            "first": name_parts[0],
            "last": name_parts[1] if len(name_parts) > 1 else "",
            "phone": payload.guest_phone,
        },
    )
    return guest_id


@router.post("/reservations")
async def reservation_webhook(
    request: Request,
    x_fortress_signature: Optional[str] = Header(None, alias="x-fortress-signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Real-time booking intake. Validates HMAC signature, upserts the reservation,
    and publishes to trust.revenue.staged for instant ledger processing.
    """
    raw_body = await request.body()

    if settings.reservation_webhook_secret:
        if not x_fortress_signature:
            raise HTTPException(status_code=401, detail="Missing X-Fortress-Signature header")
        if not _verify_hmac(raw_body, x_fortress_signature, settings.reservation_webhook_secret):
            logger.error("reservation_webhook_hmac_invalid")
            raise HTTPException(status_code=401, detail="Invalid signature")

    import json as json_mod
    try:
        body = json_mod.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        payload = ReservationWebhookPayload(**body)
    except Exception as e:
        logger.warning("reservation_webhook_validation_failed", error=str(e)[:300])
        raise HTTPException(status_code=422, detail=str(e)[:500])

    logger.info(
        "reservation_webhook_received",
        confirmation_code=payload.confirmation_code,
        event_type=payload.event_type.value,
        total_amount=float(payload.total_amount),
        booking_source=payload.booking_source,
    )

    action = await _upsert_reservation(db, payload)
    await db.commit()

    revenue_emitted = False
    if (
        payload.event_type != BookingEventType.booking_cancelled
        and float(payload.paid_amount) > 0
        and float(payload.total_amount) > 0
    ):
        if not await _already_journaled(db, payload.confirmation_code):
            revenue_payload = {
                "property_id": payload.property_id,
                "confirmation_code": payload.confirmation_code,
                "total_amount": float(payload.total_amount),
                "cleaning_fee": float(payload.cleaning_fee),
                "tax_amount": float(payload.tax_amount),
                "nightly_rate": float(payload.nightly_rate),
                "nights_count": payload.nights_count,
            }
            await EventPublisher.publish(
                "trust.revenue.staged", revenue_payload,
                key=payload.confirmation_code,
            )
            revenue_emitted = True
            logger.info(
                "reservation_revenue_emitted",
                confirmation_code=payload.confirmation_code,
                total_amount=float(payload.total_amount),
            )
        else:
            logger.info(
                "reservation_revenue_already_journaled",
                confirmation_code=payload.confirmation_code,
            )

    return {
        "status": "accepted",
        "action": action,
        "confirmation_code": payload.confirmation_code,
        "revenue_emitted": revenue_emitted,
    }
