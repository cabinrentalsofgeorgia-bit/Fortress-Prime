"""
Payments API — Staff MOTO Virtual Terminal + Payment Management.

MOTO (Mail Order / Telephone Order) enables staff to securely process
phone-order payments. All actions require StaffUser auth (manager+)
and produce SOC2-compliant audit log entries.

Per Rule 007: Financial amounts use DECIMAL, never FLOAT.
Per Rule 006: Every state-changing operation produces a structured audit log.
Per Rule 008: Responses follow RFC 7807 on errors.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_manager_or_admin
from backend.integrations.stripe_payments import StripePayments
from backend.models.staff import StaffUser

logger = structlog.get_logger()
router = APIRouter()
stripe_payments = StripePayments()


# ── Request / Response Models ──────────────────────────────────────────────

class MOTOIntentRequest(BaseModel):
    reservation_id: str = Field(..., min_length=1, description="UUID of the reservation")
    amount: Decimal = Field(..., gt=0, le=999999.99, description="Charge amount in USD")
    description: Optional[str] = Field(
        None, max_length=500,
        description="Payment description (e.g. 'Remaining balance for Cabin Creek')",
    )


class MOTOIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    amount_cents: int
    reservation_id: str
    confirmation_code: str
    guest_name: str
    property_name: str


class PaymentHistoryItem(BaseModel):
    id: str
    reservation_id: str
    confirmation_code: str
    guest_name: str
    property_name: str
    amount: str
    status: str
    created_at: str
    staff_email: str


class ReservationSearchResult(BaseModel):
    id: str
    confirmation_code: str
    guest_name: str
    property_name: str
    check_in: str
    check_out: str
    total_amount: str
    paid_amount: str
    balance_due: str
    status: str


# ── SOC2 Audit Helper ─────────────────────────────────────────────────────

async def _audit_log(
    db: AsyncSession,
    event: str,
    actor_id: str,
    actor_email: str,
    target_id: str,
    details: dict,
):
    """Write a structured audit event to analytics_events (SOC2 trail)."""
    try:
        await db.execute(
            text("""
                INSERT INTO analytics_events (id, event_type, source, data, created_at)
                VALUES (gen_random_uuid(), :event_type, :source,
                        :data::jsonb, NOW())
            """),
            {
                "event_type": event,
                "source": "moto_virtual_terminal",
                "data": str({
                    "actor_id": actor_id,
                    "actor_email": actor_email,
                    "target_id": target_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **details,
                }).replace("'", '"'),
            },
        )
        await db.commit()
    except Exception as e:
        logger.warning("audit_log_write_failed", event=event, error=str(e)[:200])


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/search-reservations")
async def search_reservations(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    """
    Search reservations by confirmation code, guest name, or property name.
    Returns matches with balance info for the MOTO terminal.
    """
    if not q or len(q) < 2:
        raise HTTPException(400, "Search query must be at least 2 characters")

    result = await db.execute(
        text("""
            SELECT r.id, r.confirmation_code,
                   COALESCE(g.first_name || ' ' || g.last_name, 'Unknown Guest') AS guest_name,
                   COALESCE(p.name, 'Unknown Property') AS property_name,
                   r.check_in_date, r.check_out_date,
                   COALESCE(r.total_amount, 0) AS total_amount,
                   COALESCE(r.paid_amount, 0) AS paid_amount,
                   COALESCE(r.balance_due, 0) AS balance_due,
                   r.status
            FROM reservations r
            LEFT JOIN guests g ON g.id = r.guest_id
            LEFT JOIN properties p ON p.id = r.property_id
            WHERE (
                r.confirmation_code ILIKE :q
                OR (g.first_name || ' ' || g.last_name) ILIKE :q
                OR p.name ILIKE :q
            )
            AND r.status NOT IN ('cancelled', 'archived')
            ORDER BY r.check_in_date DESC
            LIMIT 20
        """),
        {"q": f"%{q}%"},
    )
    rows = result.mappings().all()
    return [
        ReservationSearchResult(
            id=str(row["id"]),
            confirmation_code=row["confirmation_code"] or "",
            guest_name=row["guest_name"],
            property_name=row["property_name"],
            check_in=str(row["check_in_date"]),
            check_out=str(row["check_out_date"]),
            total_amount=str(row["total_amount"]),
            paid_amount=str(row["paid_amount"]),
            balance_due=str(row["balance_due"]),
            status=row["status"],
        )
        for row in rows
    ]


@router.post("/moto/create-intent", response_model=MOTOIntentResponse)
async def create_moto_intent(
    body: MOTOIntentRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    """
    Create a Stripe MOTO PaymentIntent for a phone/mail order.
    Requires manager or admin role.
    """
    amount_cents = int(body.amount * 100)

    if amount_cents < 50:
        raise HTTPException(400, "Minimum charge is $0.50")
    if amount_cents > 99999999:
        raise HTTPException(400, "Maximum single charge is $999,999.99")

    res = await db.execute(
        text("""
            SELECT r.id, r.confirmation_code,
                   COALESCE(g.first_name || ' ' || g.last_name, 'Unknown') AS guest_name,
                   COALESCE(p.name, 'Unknown') AS property_name,
                   r.status
            FROM reservations r
            LEFT JOIN guests g ON g.id = r.guest_id
            LEFT JOIN properties p ON p.id = r.property_id
            WHERE r.id = :rid
        """),
        {"rid": body.reservation_id},
    )
    row = res.mappings().first()
    if not row:
        raise HTTPException(404, "Reservation not found")
    if row["status"] in ("cancelled", "archived"):
        raise HTTPException(422, f"Cannot charge a {row['status']} reservation")

    description = body.description or f"MOTO payment for {row['confirmation_code']} — {row['property_name']}"

    try:
        intent = await stripe_payments.create_moto_intent(
            amount_cents=amount_cents,
            reservation_id=body.reservation_id,
            guest_name=row["guest_name"],
            description=description,
            staff_user_id=str(user.id),
            staff_email=user.email,
            confirmation_code=row["confirmation_code"] or "",
        )
    except Exception as e:
        logger.error(
            "moto_intent_creation_failed",
            error=str(e)[:500],
            reservation_id=body.reservation_id,
            staff_user_id=str(user.id),
        )
        raise HTTPException(502, f"Stripe error: {str(e)[:200]}")

    await _audit_log(
        db,
        event="moto_intent_created",
        actor_id=str(user.id),
        actor_email=user.email,
        target_id=body.reservation_id,
        details={
            "payment_intent_id": intent["payment_intent_id"],
            "amount_cents": amount_cents,
            "confirmation_code": row["confirmation_code"],
            "guest_name": row["guest_name"],
        },
    )

    return MOTOIntentResponse(
        payment_intent_id=intent["payment_intent_id"],
        client_secret=intent["client_secret"],
        amount_cents=amount_cents,
        reservation_id=body.reservation_id,
        confirmation_code=row["confirmation_code"] or "",
        guest_name=row["guest_name"],
        property_name=row["property_name"],
    )


@router.get("/history")
async def payment_history(
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    """
    List recent MOTO payment events from the audit trail.
    Paginated per Rule 008.
    """
    offset = (max(page, 1) - 1) * per_page
    per_page = min(per_page, 200)

    result = await db.execute(
        text("""
            SELECT id, event_type, source, data, created_at
            FROM analytics_events
            WHERE source = 'moto_virtual_terminal'
            AND event_type IN ('moto_intent_created', 'moto_payment_succeeded')
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": per_page, "offset": offset},
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text("""
            SELECT COUNT(*) AS total
            FROM analytics_events
            WHERE source = 'moto_virtual_terminal'
            AND event_type IN ('moto_intent_created', 'moto_payment_succeeded')
        """)
    )
    total = count_result.scalar() or 0

    return {
        "data": [
            {
                "id": str(row["id"]),
                "event_type": row["event_type"],
                "data": row["data"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, -(-total // per_page)),
        },
    }


@router.get("/stripe-key")
async def get_stripe_publishable_key(
    user: StaffUser = Depends(require_manager_or_admin),
):
    """Return the Stripe publishable key for the frontend Elements integration."""
    key = stripe_payments.get_publishable_key()
    if not key:
        raise HTTPException(503, "Stripe is not configured")
    return {"publishable_key": key}
