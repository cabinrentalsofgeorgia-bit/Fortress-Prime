"""
Reservation Webhooks — Real-Time Booking Intake Engine

Exposes POST /api/webhooks/reservations for zero-latency reservation ingestion.
When a guest books via the direct site, Streamline, or an OTA, the payload
hits this endpoint, validates via HMAC-SHA256, upserts the reservation, and
publishes to trust.revenue.staged for instant ledger journaling.

The Revenue Consumer Daemon picks up the event within milliseconds and
executes the CROG Alpha 65/35 split — all before the guest receives their
confirmation email.

Also exposes POST /api/webhooks/streamline for optional inbound Streamline
push payloads: stores the raw JSON in ``StreamlinePayloadVault`` for audit /
reconciliation. Primary guest-payment trust ledger posting remains on Stripe
webhooks (``post_checkout_trust_entry`` / ``post_invoice_clearing_entry``).
Optional structured variance posting is supported via ``fortress_trust_variance``
(see docs/streamline-trust-webhook.md).

Security: HMAC-SHA256 signature via X-Fortress-Signature header.
Auth: Public endpoint (no JWT); protected by shared secret.
"""

import hmac
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.event_publisher import EventPublisher
from backend.models.streamline_payload_vault import StreamlinePayloadVault
from backend.services.trust_ledger import post_variance_trust_entry

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


def _effective_streamline_webhook_secret() -> str:
    """Dedicated Streamline webhook secret, or the reservation webhook secret."""
    return (
        (settings.streamline_webhook_secret or settings.reservation_webhook_secret or "")
        .strip()
    )


def _normalize_json_object(raw: Any) -> dict[str, Any]:
    """Coerce parsed JSON into a dict for JSONB storage."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"_list_payload": raw}
    return {"_scalar": raw}


def _extract_event_type_from_streamline_body(body: dict[str, Any]) -> str:
    et = body.get("event_type") or body.get("eventType") or body.get("type")
    if isinstance(et, str) and et.strip():
        return et.strip()[:100]
    return "streamline_webhook"


def _extract_reservation_id_from_streamline_body(body: dict[str, Any]) -> Optional[str]:
    """Best-effort reservation / confirmation id for vault indexing."""
    for key in (
        "reservation_id",
        "reservationId",
        "streamline_reservation_id",
        "confirmation_code",
        "confirmationCode",
    ):
        v = body.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:100]
    res = body.get("reservation")
    if isinstance(res, dict):
        for key in ("id", "reservation_id", "confirmation_code"):
            v = res.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:100]
            if isinstance(v, (int, float)):
                return str(int(v))[:100]
    return None


async def _maybe_post_variance_from_streamline_payload(
    db: AsyncSession,
    body: dict[str, Any],
    reservation_id: Optional[str],
) -> str:
    """
    Optional trust-ledger variance when Streamline pushes a structured block.

    Expects ``fortress_trust_variance`` with:
    ``amount_cents``, ``debit_account_name``, ``credit_account_name``, ``event_id``,
    and optionally ``reservation_id`` (else uses extracted reservation id).
    """
    block = body.get("fortress_trust_variance")
    if not isinstance(block, dict):
        return "skipped"
    rid = block.get("reservation_id") or reservation_id
    if rid is None or (isinstance(rid, str) and not rid.strip()):
        logger.warning("streamline_webhook_variance_missing_reservation_id")
        return "skipped"
    rid_str = str(rid).strip()[:255]
    amount = block.get("amount_cents")
    debit = block.get("debit_account_name")
    credit = block.get("credit_account_name")
    event_id = block.get("event_id")
    if not isinstance(amount, int) or amount <= 0:
        return "skipped"
    if not isinstance(debit, str) or not debit.strip():
        return "skipped"
    if not isinstance(credit, str) or not credit.strip():
        return "skipped"
    if not isinstance(event_id, str) or not event_id.strip():
        return "skipped"
    await post_variance_trust_entry(
        db,
        reservation_id=rid_str,
        amount_cents=amount,
        debit_account_name=debit.strip(),
        credit_account_name=credit.strip(),
        event_id=event_id.strip()[:255],
    )
    return "posted"


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


@router.post("/streamline")
async def streamline_inbound_webhook(
    request: Request,
    x_fortress_signature: Optional[str] = Header(None, alias="x-fortress-signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inbound Streamline push: persist raw JSON to ``StreamlinePayloadVault``.

    HMAC verification uses ``STREAMLINE_WEBHOOK_SECRET`` when set; otherwise
    ``RESERVATION_WEBHOOK_SECRET`` (same behavior as ``/reservations``).
    When no secret is configured, signatures are not required (dev only).

    Guest payment trust entries remain on Stripe webhooks. Optional variance
    posting: include ``fortress_trust_variance`` (see docs/streamline-trust-webhook.md).
    """
    raw_body = await request.body()
    secret = _effective_streamline_webhook_secret()
    if secret:
        if not x_fortress_signature:
            raise HTTPException(status_code=401, detail="Missing X-Fortress-Signature header")
        if not _verify_hmac(raw_body, x_fortress_signature, secret):
            logger.error("streamline_webhook_hmac_invalid")
            raise HTTPException(status_code=401, detail="Invalid signature")

    import json as json_mod

    try:
        parsed = json_mod.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    body = _normalize_json_object(parsed)
    event_type = _extract_event_type_from_streamline_body(body)
    reservation_id = _extract_reservation_id_from_streamline_body(body)

    vault_row = StreamlinePayloadVault(
        event_type=event_type,
        raw_payload=body,
        reservation_id=reservation_id,
    )
    db.add(vault_row)
    await db.flush()

    trust_ledger = "skipped"
    try:
        trust_ledger = await _maybe_post_variance_from_streamline_payload(
            db, body, reservation_id
        )
    except ValueError as exc:
        logger.warning("streamline_webhook_variance_value_error", error=str(exc)[:300])
        trust_ledger = "error"
    except Exception:
        logger.exception("streamline_webhook_variance_failed")
        trust_ledger = "error"

    await db.commit()

    logger.info(
        "streamline_webhook_accepted",
        vault_id=str(vault_row.id),
        event_type=event_type,
        reservation_id=reservation_id,
        trust_ledger=trust_ledger,
    )

    return {
        "status": "accepted",
        "vault_id": str(vault_row.id),
        "event_type": event_type,
        "reservation_id": reservation_id,
        "trust_ledger": trust_ledger,
    }
