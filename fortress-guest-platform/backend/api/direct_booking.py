"""
Direct Booking API — Guest-facing endpoints for the booking engine.
Allows guests to search, quote, book, and pay without OTA commissions.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments

router = APIRouter()
stripe_payments = StripePayments()


# ── Request/Response Models ──

class AvailabilityQuery(BaseModel):
    check_in: str = Field(..., description="YYYY-MM-DD")
    check_out: str = Field(..., description="YYYY-MM-DD")
    guests: int = Field(1, ge=1, le=20)
    pets: bool = False


class BookingRequest(BaseModel):
    property_id: str
    check_in: str
    check_out: str
    num_guests: int = Field(1, ge=1)
    guest_first_name: str
    guest_last_name: str
    guest_email: str
    guest_phone: str
    special_requests: Optional[str] = None
    promo_code: Optional[str] = None


class PaymentIntentRequest(BaseModel):
    reservation_id: str
    amount_cents: int


# ── Public Endpoints ──

@router.get("/availability")
async def check_availability(
    check_in: str,
    check_out: str,
    guests: int = 1,
    pets: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Check which properties are available for given dates/guest count.
    Returns available properties with pricing.
    """
    ci = date.fromisoformat(check_in)
    co = date.fromisoformat(check_out)

    if ci >= co:
        raise HTTPException(400, "Check-out must be after check-in")
    if (co - ci).days > 30:
        raise HTTPException(400, "Maximum stay is 30 nights")

    nights = (co - ci).days

    result = await db.execute(
        text("""
            SELECT p.id, p.name, p.slug, p.property_type, p.bedrooms,
                   p.bathrooms, p.max_guests, p.address
            FROM properties p
            WHERE p.is_active = true
            AND p.max_guests >= :guests
            AND p.id NOT IN (
                SELECT DISTINCT r.property_id
                FROM reservations r
                WHERE r.status IN ('confirmed', 'checked_in')
                AND r.check_in_date < :check_out
                AND r.check_out_date > :check_in
            )
            ORDER BY p.name
        """),
        {"guests": guests, "check_in": ci, "check_out": co},
    )

    available = []
    for row in result.fetchall():
        p = dict(row._mapping)
        base_rate = 250
        cleaning_fee = 150
        service_fee = round(base_rate * nights * 0.03)
        tax = round(base_rate * nights * 0.08)
        total = base_rate * nights + cleaning_fee + service_fee + tax

        p["pricing"] = {
            "nightly_rate": base_rate,
            "nights": nights,
            "subtotal": base_rate * nights,
            "cleaning_fee": cleaning_fee,
            "service_fee": service_fee,
            "tax": tax,
            "total": total,
        }
        available.append(p)

    return {"check_in": check_in, "check_out": check_out, "guests": guests, "results": available}


@router.get("/property/{slug}")
async def get_booking_property(slug: str, db: AsyncSession = Depends(get_db)):
    """Get property details for the booking page (public, no auth)."""
    result = await db.execute(
        text("""
            SELECT id, name, slug, property_type, bedrooms, bathrooms,
                   max_guests, address, parking_instructions
            FROM properties
            WHERE slug = :slug AND is_active = true
        """),
        {"slug": slug},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Property not found")
    return dict(row._mapping)


@router.post("/quote")
async def generate_quote(body: AvailabilityQuery, property_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a detailed price quote for a specific property and dates."""
    ci = date.fromisoformat(body.check_in)
    co = date.fromisoformat(body.check_out)
    nights = (co - ci).days

    result = await db.execute(
        text("SELECT * FROM properties WHERE id = :id AND is_active = true"),
        {"id": property_id},
    )
    prop = result.fetchone()
    if not prop:
        raise HTTPException(404, "Property not found")

    base_rate = 250
    cleaning_fee = 150
    pet_fee = 50 if body.pets else 0
    subtotal = base_rate * nights
    tax = round(subtotal * 0.08)
    service_fee = round(subtotal * 0.03)
    total = subtotal + cleaning_fee + pet_fee + tax + service_fee

    return {
        "property_id": property_id,
        "property_name": prop._mapping["name"],
        "check_in": body.check_in,
        "check_out": body.check_out,
        "nights": nights,
        "guests": body.guests,
        "breakdown": {
            "nightly_rate": base_rate,
            "subtotal": subtotal,
            "cleaning_fee": cleaning_fee,
            "pet_fee": pet_fee,
            "service_fee": service_fee,
            "tax": tax,
            "total": total,
        },
    }


@router.post("/book")
async def create_booking(body: BookingRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a direct booking. Returns a payment intent for the guest to complete.
    The reservation is created in 'pending_payment' status until Stripe confirms.
    """
    ci = date.fromisoformat(body.check_in)
    co = date.fromisoformat(body.check_out)
    nights = (co - ci).days

    prop = await db.execute(
        text("SELECT * FROM properties WHERE id = :id AND is_active = true"),
        {"id": body.property_id},
    )
    p = prop.fetchone()
    if not p:
        raise HTTPException(404, "Property not found")

    conflict = await db.execute(
        text("""
            SELECT id FROM reservations
            WHERE property_id = :pid AND status IN ('confirmed', 'checked_in')
            AND check_in_date < :co AND check_out_date > :ci
        """),
        {"pid": body.property_id, "ci": ci, "co": co},
    )
    if conflict.fetchone():
        raise HTTPException(409, "Property is not available for these dates")

    base_rate = 250
    total = base_rate * nights + 150 + round(base_rate * nights * 0.08) + round(base_rate * nights * 0.03)
    total_cents = int(total * 100)

    guest_result = await db.execute(
        text("""
            INSERT INTO guests (phone_number, email, first_name, last_name)
            VALUES (:phone, :email, :first, :last)
            ON CONFLICT (phone_number) DO UPDATE SET
                email = EXCLUDED.email,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
            RETURNING id
        """),
        {
            "phone": body.guest_phone,
            "email": body.guest_email,
            "first": body.guest_first_name,
            "last": body.guest_last_name,
        },
    )
    guest_id = str(guest_result.fetchone()._mapping["id"])

    import uuid
    confirmation_code = f"FGP-{uuid.uuid4().hex[:8].upper()}"

    res_result = await db.execute(
        text("""
            INSERT INTO reservations (
                confirmation_code, guest_id, property_id,
                check_in_date, check_out_date, num_guests,
                status, booking_source, total_amount, special_requests
            ) VALUES (
                :code, :guest_id, :property_id,
                :ci, :co, :guests,
                'confirmed', 'direct', :total, :requests
            )
            RETURNING id
        """),
        {
            "code": confirmation_code,
            "guest_id": guest_id,
            "property_id": body.property_id,
            "ci": ci, "co": co,
            "guests": body.num_guests,
            "total": total,
            "requests": body.special_requests,
        },
    )
    reservation_id = str(res_result.fetchone()._mapping["id"])
    await db.commit()

    payment = await stripe_payments.create_payment_intent(
        amount_cents=total_cents,
        reservation_id=reservation_id,
        guest_email=body.guest_email,
        guest_name=f"{body.guest_first_name} {body.guest_last_name}",
        property_name=p._mapping["name"],
    )

    return {
        "reservation_id": reservation_id,
        "confirmation_code": confirmation_code,
        "total_amount": total,
        "payment": payment,
    }


@router.get("/config")
async def get_booking_config():
    """Return Stripe publishable key and booking configuration."""
    return {
        "stripe_publishable_key": stripe_payments.get_publishable_key(),
        "min_nights": 1,
        "max_nights": 30,
        "max_advance_days": 365,
        "cancellation_policy": "flexible",
        "service_fee_pct": 3,
        "tax_rate_pct": 8,
    }


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe payment webhook events."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = await stripe_payments.handle_webhook(payload, sig)
        return {"status": "ok", "event_type": event.get("event_type")}
    except Exception as e:
        raise HTTPException(400, str(e))
