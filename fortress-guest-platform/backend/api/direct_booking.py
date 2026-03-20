"""
Direct Booking API — Guest-facing endpoints for the booking engine.
Allows guests to search, quote, book, and pay without OTA commissions.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments
from backend.models.guest import Guest
from backend.models.property import Property
from backend.services.openshell_audit import record_audit_event
from backend.services.reservation_engine import ReservationEngine

router = APIRouter()
stripe_payments = StripePayments()
reservation_engine = ReservationEngine()


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

    properties = (
        await db.execute(
            select(Property)
            .where(Property.is_active.is_(True))
            .where(Property.max_guests >= guests)
            .order_by(Property.name.asc())
        )
    ).scalars().all()

    available = []
    for prop in properties:
        is_available = await reservation_engine.get_availability(db, prop.id, ci, co)
        if not is_available:
            continue
        pricing = await reservation_engine.calculate_pricing(db, prop.id, ci, co, guests=guests)
        available.append(
            {
                "id": str(prop.id),
                "name": prop.name,
                "slug": prop.slug,
                "property_type": prop.property_type,
                "bedrooms": prop.bedrooms,
                "bathrooms": float(prop.bathrooms) if prop.bathrooms is not None else None,
                "max_guests": prop.max_guests,
                "address": prop.address,
                "pricing": pricing,
            }
        )

    await record_audit_event(
        action="reservation.availability.read",
        resource_type="reservation",
        purpose="direct_booking",
        tool_name="direct_booking_check_availability",
        model_route="tool",
        outcome="success",
        request_id=None,
        metadata_json={
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
            "pets": pets,
            "result_count": len(available),
        },
        db=db,
    )

    return {"check_in": check_in, "check_out": check_out, "guests": guests, "results": available}


@router.get("/property/{slug}")
async def get_booking_property(slug: str, db: AsyncSession = Depends(get_db)):
    """Get property details for the booking page (public, no auth)."""
    result = await db.execute(
        text("""
            SELECT id, name, slug, property_type, bedrooms, bathrooms,
                   max_guests, address, parking_instructions, streamline_property_id
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
    prop = await db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    pricing = await reservation_engine.calculate_pricing(db, prop.id, ci, co, guests=body.guests)
    pet_fee = 50 if body.pets else 0
    total = float(pricing["total"]) + pet_fee

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "check_in": body.check_in,
        "check_out": body.check_out,
        "nights": pricing["nights"],
        "guests": body.guests,
        "breakdown": {
            "nightly_rate": pricing["base_rate"],
            "subtotal": pricing["subtotal"],
            "cleaning_fee": 0,
            "pet_fee": pet_fee,
            "service_fee": 0,
            "tax": 0,
            "total": total,
            "nightly_breakdown": pricing["nightly_breakdown"],
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
    prop = await db.get(Property, body.property_id)
    if not prop or not prop.is_active:
        raise HTTPException(404, "Property not found")

    if not await reservation_engine.get_availability(db, prop.id, ci, co):
        raise HTTPException(409, "Property is not available for these dates")

    guest = (
        await db.execute(select(Guest).where(Guest.phone_number == body.guest_phone))
    ).scalar_one_or_none()
    if guest is None:
        guest = Guest(
            phone_number=body.guest_phone,
            email=body.guest_email,
            first_name=body.guest_first_name,
            last_name=body.guest_last_name,
        )
        db.add(guest)
        await db.flush()
    else:
        guest.email = body.guest_email
        guest.first_name = body.guest_first_name
        guest.last_name = body.guest_last_name

    pricing = await reservation_engine.calculate_pricing(db, prop.id, ci, co, guests=body.num_guests)
    total = Decimal(str(pricing["total"]))
    total_cents = int(total * 100)

    reservation = await reservation_engine.create_reservation(
        db,
        {
            "guest_id": guest.id,
            "property_id": prop.id,
            "check_in_date": ci,
            "check_out_date": co,
            "num_guests": body.num_guests,
            "booking_source": "direct",
            "total_amount": total,
            "internal_notes": body.special_requests,
        },
    )
    reservation.status = "pending_payment"
    reservation.special_requests = body.special_requests
    await db.commit()

    payment = await stripe_payments.create_payment_intent(
        amount_cents=total_cents,
        reservation_id=str(reservation.id),
        guest_email=body.guest_email,
        guest_name=f"{body.guest_first_name} {body.guest_last_name}",
        property_name=prop.name,
    )

    await record_audit_event(
        action="reservation.booking.create",
        resource_type="reservation",
        resource_id=str(reservation.id),
        purpose="direct_booking",
        tool_name="direct_booking_create",
        redaction_status="contains_pii_local_only",
        model_route="tool",
        outcome="success",
        metadata_json={
            "property_id": str(prop.id),
            "guest_phone": body.guest_phone[-4:],
            "check_in": body.check_in,
            "check_out": body.check_out,
            "status": reservation.status,
            "total_amount": str(total),
        },
    )

    return {
        "reservation_id": str(reservation.id),
        "confirmation_code": reservation.confirmation_code,
        "total_amount": float(total),
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
