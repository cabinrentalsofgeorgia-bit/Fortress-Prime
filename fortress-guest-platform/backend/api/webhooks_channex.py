"""
Channex webhooks — signed ingress + immutable ledger + async handoff.

Ingress validates ``x-channex-signature`` as HMAC-SHA256 over the raw request
body, persists the exact validated event JSON into an immutable Postgres ledger,
and returns ``202 Accepted`` immediately so the upstream channel manager is not
blocked on downstream reservation processing.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import structlog

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, get_db

logger = structlog.get_logger(service="webhooks_channex")
router = APIRouter()


def _verify_signature(payload: bytes, signature: str | None) -> bool:
    secret = str(settings.channex_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CHANNEX_WEBHOOK_SECRET is not configured",
        )
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


class ChannexCustomer(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None


class ChannexBookingPayload(BaseModel):
    booking_id: str = Field(..., min_length=1, max_length=255)
    property_id: str = Field(..., min_length=1, max_length=255)
    ota_source: str = Field(..., min_length=1, max_length=100)
    status: str = Field(..., min_length=1, max_length=50)
    check_in_date: datetime
    check_out_date: datetime
    customer: ChannexCustomer
    total_price: float
    currency: str = "USD"
    raw_data: dict[str, object] = Field(default_factory=dict)


class ChannexWebhookEvent(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=1, max_length=100)
    timestamp: datetime
    payload: ChannexBookingPayload


def _normalize_booking_status(event_type: str, booking_status: str) -> str:
    raw = f"{event_type} {booking_status}".lower()
    if "cancel" in raw:
        return "booking_cancelled"
    if "modify" in raw or "update" in raw:
        return "booking_updated"
    return "booking_created"


async def _resolve_property_uuid(db: AsyncSession, property_ref: str) -> str | None:
    result = await db.execute(
        text(
            """
            SELECT id::text
            FROM properties
            WHERE ota_metadata->>'channex_listing_id' = :ref
            LIMIT 1
            """
        ),
        {"ref": property_ref},
    )
    row = result.first()
    return str(row[0]) if row else None


def _synthetic_phone(email: str, phone: str | None) -> str:
    candidate = (phone or "").strip()
    if candidate:
        return candidate
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    digits = "".join(str(int(ch, 16) % 10) for ch in digest[:10])
    return f"+1888{digits}"


async def _upsert_guest_for_channex(
    db: AsyncSession,
    payload: ChannexBookingPayload,
) -> str | None:
    email = (payload.customer.email or "").strip().lower()
    phone = _synthetic_phone(email, payload.customer.phone)
    if not email:
        return None

    existing = await db.execute(
        text("SELECT id FROM guests WHERE email = :email LIMIT 1"),
        {"email": email},
    )
    row = existing.first()
    if row:
        await db.execute(
            text(
                """
                UPDATE guests
                SET first_name = COALESCE(:first_name, first_name),
                    last_name = COALESCE(:last_name, last_name),
                    phone = COALESCE(NULLIF(:phone, ''), phone),
                    updated_at = NOW()
                WHERE id = :guest_id
                """
            ),
            {
                "guest_id": row.id,
                "first_name": payload.customer.first_name,
                "last_name": payload.customer.last_name,
                "phone": phone,
            },
        )
        return str(row.id)

    guest_id = await db.execute(
        text(
            """
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
                updated_at,
                first_booking_source
            )
            VALUES (
                gen_random_uuid(),
                :email,
                :first_name,
                :last_name,
                :phone,
                :guest_source,
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
                NOW(),
                :first_booking_source
            )
            RETURNING id::text
            """
        ),
        {
            "email": email,
            "first_name": payload.customer.first_name,
            "last_name": payload.customer.last_name,
            "phone": phone,
            "guest_source": payload.ota_source.lower(),
            "first_booking_source": payload.ota_source.lower(),
            "preferences": "{}",
        },
    )
    return guest_id.scalar_one()


async def _upsert_reservation_from_channex(
    db: AsyncSession,
    event: ChannexWebhookEvent,
) -> str:
    payload = event.payload
    property_uuid = await _resolve_property_uuid(db, payload.property_id)
    if not property_uuid:
        raise RuntimeError(f"Unable to map Channex property reference '{payload.property_id}'")

    guest_id = await _upsert_guest_for_channex(db, payload)
    reservation_status = _normalize_booking_status(event.event_type, payload.status)
    amount = float(payload.total_price or 0)
    guest_count = int(payload.raw_data.get("num_guests") or payload.raw_data.get("guest_count") or 1)

    existing = await db.execute(
        text("SELECT id FROM reservations WHERE confirmation_code = :code LIMIT 1"),
        {"code": payload.booking_id},
    )
    row = existing.first()
    if row:
        await db.execute(
            text(
                """
                UPDATE reservations
                SET property_id = CAST(:property_id AS uuid),
                    guest_id = COALESCE(CAST(:guest_id AS uuid), guest_id),
                    check_in_date = :check_in_date,
                    check_out_date = :check_out_date,
                    total_amount = :total_amount,
                    paid_amount = :paid_amount,
                    balance_due = 0,
                    num_guests = :num_guests,
                    status = :status,
                    booking_source = :booking_source,
                    currency = :currency,
                    streamline_reservation_id = :external_id,
                    updated_at = NOW()
                WHERE confirmation_code = :confirmation_code
                """
            ),
            {
                "property_id": property_uuid,
                "guest_id": guest_id,
                "check_in_date": payload.check_in_date.date(),
                "check_out_date": payload.check_out_date.date(),
                "total_amount": amount,
                "paid_amount": amount if reservation_status != "booking_cancelled" else 0,
                "num_guests": guest_count,
                "status": "cancelled" if reservation_status == "booking_cancelled" else "confirmed",
                "booking_source": payload.ota_source.lower(),
                "currency": payload.currency,
                "external_id": payload.booking_id,
                "confirmation_code": payload.booking_id,
            },
        )
        return "updated"

    await db.execute(
        text(
            """
            INSERT INTO reservations (
                id,
                confirmation_code,
                property_id,
                guest_id,
                check_in_date,
                check_out_date,
                total_amount,
                paid_amount,
                balance_due,
                num_guests,
                status,
                booking_source,
                currency,
                streamline_reservation_id,
                created_at,
                updated_at
            )
            VALUES (
                gen_random_uuid(),
                :confirmation_code,
                CAST(:property_id AS uuid),
                CAST(:guest_id AS uuid),
                :check_in_date,
                :check_out_date,
                :total_amount,
                :paid_amount,
                0,
                :num_guests,
                :status,
                :booking_source,
                :currency,
                :external_id,
                NOW(),
                NOW()
            )
            """
        ),
        {
            "confirmation_code": payload.booking_id,
            "property_id": property_uuid,
            "guest_id": guest_id,
            "check_in_date": payload.check_in_date.date(),
            "check_out_date": payload.check_out_date.date(),
            "total_amount": amount,
            "paid_amount": amount if reservation_status != "booking_cancelled" else 0,
            "num_guests": guest_count,
            "status": "cancelled" if reservation_status == "booking_cancelled" else "confirmed",
            "booking_source": payload.ota_source.lower(),
            "currency": payload.currency,
            "external_id": payload.booking_id,
        },
    )
    return "created"


async def process_channex_event_worker(ledger_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT id::text, raw_payload
                        FROM channex_webhook_events
                        WHERE id::text = :ledger_id
                        LIMIT 1
                        """
                    ),
                    {"ledger_id": ledger_id},
                )
            ).mappings().first()
            if not row:
                logger.error("channex_worker_ledger_missing", ledger_id=ledger_id)
                return

            await db.execute(
                text(
                    """
                    UPDATE channex_webhook_events
                    SET processing_status = 'processing',
                        processing_attempts = processing_attempts + 1,
                        processing_error = NULL
                    WHERE id::text = :ledger_id
                    """
                ),
                {"ledger_id": ledger_id},
            )
            await db.commit()

            event = ChannexWebhookEvent.model_validate(row["raw_payload"])
            reservation_action = "ignored"
            if event.event_type.lower().startswith("booking_"):
                reservation_action = await _upsert_reservation_from_channex(db, event)
                await db.commit()

            await db.execute(
                text(
                    """
                    UPDATE channex_webhook_events
                    SET processing_status = 'processed',
                        processed_at = NOW(),
                        reservation_action = :reservation_action
                    WHERE id::text = :ledger_id
                    """
                ),
                {
                    "ledger_id": ledger_id,
                    "reservation_action": reservation_action,
                },
            )
            await db.commit()
            logger.info(
                "channex_worker_processed",
                ledger_id=ledger_id,
                event_id=event.event_id,
                event_type=event.event_type,
                reservation_action=reservation_action,
            )
        except Exception as exc:
            await db.rollback()
            await db.execute(
                text(
                    """
                    UPDATE channex_webhook_events
                    SET processing_status = 'failed',
                        processed_at = NOW(),
                        processing_error = :processing_error
                    WHERE id::text = :ledger_id
                    """
                ),
                {
                    "ledger_id": ledger_id,
                    "processing_error": str(exc)[:1000],
                },
            )
            await db.commit()
            logger.error("channex_worker_failed", ledger_id=ledger_id, error=str(exc)[:300])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def ingest_channex_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    channex_signature: str | None = Header(default=None, alias="x-channex-signature"),
):
    raw_body = await request.body()
    if not _verify_signature(raw_body, channex_signature):
        logger.warning("channex_signature_invalid")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Channex signature",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        logger.warning("channex_payload_invalid_json", error=str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    try:
        event = ChannexWebhookEvent.model_validate(payload)
    except Exception as exc:
        logger.warning("channex_payload_validation_failed", error=str(exc)[:300])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Channex event payload",
        ) from exc

    logger.info(
        "channex_webhook_received",
        event_id=event.event_id,
        event_type=event.event_type,
        listing_id=event.payload.property_id,
        body_size=len(raw_body),
    )

    ledger_insert = await db.execute(
        text(
            """
            INSERT INTO channex_webhook_events (
                id,
                event_id,
                event_type,
                event_timestamp,
                booking_id,
                property_ref,
                ota_source,
                booking_status,
                raw_payload,
                processing_status,
                processing_attempts,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                :event_id,
                :event_type,
                :event_timestamp,
                :booking_id,
                :property_ref,
                :ota_source,
                :booking_status,
                CAST(:raw_payload AS jsonb),
                'pending',
                0,
                NOW()
            )
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id::text
            """
        ),
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_timestamp": event.timestamp,
            "booking_id": event.payload.booking_id,
            "property_ref": event.payload.property_id,
            "ota_source": event.payload.ota_source,
            "booking_status": event.payload.status,
            "raw_payload": json.dumps(payload),
        },
    )
    ledger_id = ledger_insert.scalar_one_or_none()
    duplicate = ledger_id is None
    if duplicate:
        existing = await db.execute(
            text("SELECT id::text FROM channex_webhook_events WHERE event_id = :event_id LIMIT 1"),
            {"event_id": event.event_id},
        )
        ledger_id = existing.scalar_one()
    await db.commit()

    if not duplicate:
        background_tasks.add_task(process_channex_event_worker, ledger_id)

    return {
        "status": "accepted",
        "event_id": event.event_id,
        "ledger_id": ledger_id,
        "duplicate": duplicate,
    }
