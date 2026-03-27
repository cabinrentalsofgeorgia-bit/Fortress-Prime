"""
Direct Booking API — Guest-facing endpoints for the booking engine.
Allows guests to search, quote, book, and pay without OTA commissions.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments
from backend.models.property import Property
from backend.models.reservation_hold import ReservationHold
from backend.services.booking_hold_service import (
    BookingHoldError,
    convert_hold_to_reservation,
    create_checkout_hold,
    finalize_hold_as_reservation,
)
from backend.services.fast_quote_service import (
    FastQuoteError,
    calculate_locked_fast_quote_breakdown,
)
from backend.services.sovereign_checkout_quote import issue_signed_checkout_quote
from backend.core.config import settings
from backend.services.funnel_identity_bridge import record_hold_intent_bridge
from backend.services.openshell_audit import record_audit_event
from backend.services.property_availability_cache import get_property_availability_month
from backend.services.reservation_engine import ReservationEngine

router = APIRouter()
stripe_payments = StripePayments()
reservation_engine = ReservationEngine()


# ── Request/Response Models ──

class AvailabilityQuery(BaseModel):
    check_in: str = Field(..., description="YYYY-MM-DD")
    check_out: str = Field(..., description="YYYY-MM-DD")
    guests: int = Field(1, ge=1, le=20)
    adults: int | None = Field(default=None, ge=1)
    children: int | None = Field(default=None, ge=0)
    pets: int = Field(0, ge=0, le=12)

    @field_validator("pets", mode="before")
    @classmethod
    def _coerce_pets(cls, value: object) -> int:
        if isinstance(value, bool):
            return 1 if value else 0
        if value is None:
            return 0
        return int(value)


class BookingRequest(BaseModel):
    property_id: str
    check_in: str
    check_out: str
    num_guests: int = Field(1, ge=1)
    adults: int | None = Field(default=None, ge=1)
    children: int | None = Field(default=None, ge=0)
    pets: int = Field(0, ge=0, le=12)
    session_id: str | None = None
    guest_first_name: str
    guest_last_name: str
    guest_email: str
    guest_phone: str
    special_requests: Optional[str] = None
    promo_code: Optional[str] = None
    signed_quote: dict[str, Any] | None = None
    intent_session_id: UUID | None = Field(
        default=None,
        description="First-party storefront session UUID (intent lane); used only after submit to bridge fingerprint → guest.",
    )

    @field_validator("pets", mode="before")
    @classmethod
    def _coerce_booking_pets(cls, value: object) -> int:
        if isinstance(value, bool):
            return 1 if value else 0
        if value is None:
            return 0
        return int(value)


class PaymentIntentRequest(BaseModel):
    reservation_id: str
    amount_cents: int


class ConfirmHoldRequest(BaseModel):
    hold_id: str


class AvailabilityPricingResponse(BaseModel):
    nightly_rate: float
    nights: int
    subtotal: float
    cleaning_fee: float
    service_fee: float
    tax: float
    total: float


class AvailablePropertyResponse(BaseModel):
    id: str
    name: str
    slug: str
    property_type: str
    bedrooms: int
    bathrooms: float | None
    max_guests: int
    address: str | None
    pricing: AvailabilityPricingResponse


class AvailabilityResponse(BaseModel):
    check_in: str
    check_out: str
    guests: int
    results: list[AvailablePropertyResponse]


class PropertyImageResponse(BaseModel):
    id: str
    property_id: str
    legacy_url: str
    sovereign_url: str | None = None
    display_order: int
    alt_text: str
    is_hero: bool
    status: str


class BookingPropertyResponse(BaseModel):
    id: str
    name: str
    slug: str
    property_type: str
    bedrooms: int
    bathrooms: float | None
    max_guests: int
    address: str | None
    parking_instructions: str | None
    streamline_property_id: str | None
    images: list[PropertyImageResponse]
    availability: dict[str, Any] | None = None


class PropertyCalendarResponse(BaseModel):
    property_id: str
    property_slug: str
    month: int
    year: int
    start_date: str
    end_date: str
    blocked_dates: list[str]
    blocked_dates_count: int
    available_dates_count: int
    generated_at: str


class PropertyCalendarDayCellResponse(BaseModel):
    date: str
    status: str
    available: bool
    nightly_rate: float | None
    season: str
    multiplier: float


class PropertyCalendarV2Response(PropertyCalendarResponse):
    month_grid: dict[str, PropertyCalendarDayCellResponse]
    pricing_source: str
    availability_source: str


class FleetCalendarPropertySummaryResponse(BaseModel):
    property_id: str
    property_name: str
    slug: str
    property_type: str
    bedrooms: int
    bathrooms: float | None
    max_guests: int
    address: str | None
    month_grid: dict[str, PropertyCalendarDayCellResponse]
    summary: dict[str, float | int]


class FleetCalendarV2Response(BaseModel):
    month: int
    year: int
    start_date: str
    end_date: str
    generated_at: str
    property_count: int
    pricing_source: str
    availability_source: str
    properties: list[FleetCalendarPropertySummaryResponse]


# ── Public Endpoints ──

@router.get("/availability", response_model=AvailabilityResponse)
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
        is_available = await reservation_engine.get_availability(
            db,
            prop.id,
            ci,
            co,
        )
        if not is_available:
            continue
        raw_pricing = await reservation_engine.calculate_pricing(db, prop.id, ci, co, guests=guests)
        nights = int(raw_pricing["nights"])
        subtotal = float(raw_pricing["subtotal"])
        extra_guest_fee = float(raw_pricing.get("extra_guest_fee", 0))
        total = float(raw_pricing["total"])
        nightly_rate = round(subtotal / nights, 2) if nights else 0.0
        pricing = {
            "nightly_rate": nightly_rate,
            "nights": nights,
            "subtotal": subtotal,
            "cleaning_fee": 0.0,
            "service_fee": extra_guest_fee,
            "tax": 0.0,
            "total": total,
        }
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


@router.get("/property/{slug}", response_model=BookingPropertyResponse)
async def get_booking_property(slug: str, db: AsyncSession = Depends(get_db)):
    """Get property details for the booking page (public, no auth)."""
    property_record = (
        await db.execute(
            select(Property)
            .options(selectinload(Property.images))
            .where(Property.slug == slug)
            .where(Property.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if property_record is None:
        raise HTTPException(404, "Property not found")

    return BookingPropertyResponse(
        id=str(property_record.id),
        name=property_record.name,
        slug=property_record.slug,
        property_type=property_record.property_type,
        bedrooms=property_record.bedrooms,
        bathrooms=float(property_record.bathrooms) if property_record.bathrooms is not None else None,
        max_guests=property_record.max_guests,
        address=property_record.address,
        parking_instructions=property_record.parking_instructions,
        streamline_property_id=property_record.streamline_property_id,
        images=[
            PropertyImageResponse(
                id=str(image.id),
                property_id=str(image.property_id),
                legacy_url=image.legacy_url,
                sovereign_url=image.sovereign_url,
                display_order=image.display_order,
                alt_text=image.alt_text,
                is_hero=image.is_hero,
                status=image.status,
            )
            for image in property_record.images
        ],
        availability=get_property_availability_month(property_record.availability),
    )


@router.get("/property/{slug}/calendar", response_model=PropertyCalendarResponse)
async def get_property_calendar(
    slug: str,
    month: int,
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """Return a flat blocked-date calendar for a property from the local ledger."""
    if month < 1 or month > 12:
        raise HTTPException(400, "Month must be between 1 and 12")
    if year < 2024 or year > 2100:
        raise HTTPException(400, "Year is outside the supported calendar range")

    property_record = (
        await db.execute(
            select(Property)
            .where(Property.slug == slug)
            .where(Property.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if property_record is None:
        raise HTTPException(404, "Property not found")

    calendar_payload = await reservation_engine.get_blocked_dates_for_month(
        db,
        property_record.id,
        month,
        year,
    )

    await record_audit_event(
        action="reservation.calendar.read",
        resource_type="property",
        purpose="direct_booking",
        tool_name="direct_booking_property_calendar",
        model_route="tool",
        outcome="success",
        request_id=None,
        metadata_json={
            "property_id": str(property_record.id),
            "property_slug": property_record.slug,
            "month": month,
            "year": year,
            "blocked_dates_count": calendar_payload["blocked_dates_count"],
        },
        db=db,
    )

    return PropertyCalendarResponse(
        property_id=str(property_record.id),
        property_slug=property_record.slug,
        month=calendar_payload["month"],
        year=calendar_payload["year"],
        start_date=calendar_payload["start_date"],
        end_date=calendar_payload["end_date"],
        blocked_dates=calendar_payload["blocked_dates"],
        blocked_dates_count=calendar_payload["blocked_dates_count"],
        available_dates_count=calendar_payload["available_dates_count"],
        generated_at=calendar_payload["generated_at"],
    )


@router.get("/property/{slug}/calendar-v2", response_model=PropertyCalendarV2Response)
async def get_property_calendar_v2(
    slug: str,
    month: int,
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """Return month-grid availability with local nightly-rate hints."""
    if month < 1 or month > 12:
        raise HTTPException(400, "Month must be between 1 and 12")
    if year < 2024 or year > 2100:
        raise HTTPException(400, "Year is outside the supported calendar range")

    property_record = (
        await db.execute(
            select(Property)
            .where(Property.slug == slug)
            .where(Property.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if property_record is None:
        raise HTTPException(404, "Property not found")

    calendar_payload = await reservation_engine.get_calendar_v2(
        db,
        property_record.id,
        month,
        year,
    )

    await record_audit_event(
        action="reservation.calendar_v2.read",
        resource_type="property",
        purpose="direct_booking",
        tool_name="direct_booking_property_calendar_v2",
        model_route="tool",
        outcome="success",
        request_id=None,
        metadata_json={
            "property_id": str(property_record.id),
            "property_slug": property_record.slug,
            "month": month,
            "year": year,
            "blocked_dates_count": calendar_payload["blocked_dates_count"],
            "available_dates_count": calendar_payload["available_dates_count"],
        },
        db=db,
    )

    return PropertyCalendarV2Response(
        property_id=str(property_record.id),
        property_slug=property_record.slug,
        month=calendar_payload["month"],
        year=calendar_payload["year"],
        start_date=calendar_payload["start_date"],
        end_date=calendar_payload["end_date"],
        blocked_dates=calendar_payload["blocked_dates"],
        blocked_dates_count=calendar_payload["blocked_dates_count"],
        available_dates_count=calendar_payload["available_dates_count"],
        generated_at=calendar_payload["generated_at"],
        month_grid={
            date_key: PropertyCalendarDayCellResponse(**cell)
            for date_key, cell in calendar_payload["month_grid"].items()
        },
        pricing_source=calendar_payload["pricing_source"],
        availability_source=calendar_payload["availability_source"],
    )


@router.get("/fleet/calendar-v2", response_model=FleetCalendarV2Response)
async def get_fleet_calendar_v2(
    month: int,
    year: int,
    db: AsyncSession = Depends(get_db),
):
    """Return a single SSR-friendly month grid for every active property."""
    if month < 1 or month > 12:
        raise HTTPException(400, "Month must be between 1 and 12")
    if year < 2024 or year > 2100:
        raise HTTPException(400, "Year is outside the supported calendar range")

    fleet_payload = await reservation_engine.get_fleet_calendar_v2(db, month, year)

    await record_audit_event(
        action="reservation.calendar_v2_bulk.read",
        resource_type="property",
        purpose="direct_booking",
        tool_name="direct_booking_fleet_calendar_v2",
        model_route="tool",
        outcome="success",
        request_id=None,
        metadata_json={
            "month": month,
            "year": year,
            "property_count": fleet_payload["property_count"],
        },
        db=db,
    )

    return FleetCalendarV2Response(
        month=fleet_payload["month"],
        year=fleet_payload["year"],
        start_date=fleet_payload["start_date"],
        end_date=fleet_payload["end_date"],
        generated_at=fleet_payload["generated_at"],
        property_count=fleet_payload["property_count"],
        pricing_source=fleet_payload["pricing_source"],
        availability_source=fleet_payload["availability_source"],
        properties=[
            FleetCalendarPropertySummaryResponse(
                property_id=row["property_id"],
                property_name=row["property_name"],
                slug=row["slug"],
                property_type=row["property_type"],
                bedrooms=row["bedrooms"],
                bathrooms=row["bathrooms"],
                max_guests=row["max_guests"],
                address=row["address"],
                month_grid={
                    date_key: PropertyCalendarDayCellResponse(**cell)
                    for date_key, cell in row["month_grid"].items()
                },
                summary=row["summary"],
            )
            for row in fleet_payload["properties"]
        ],
    )


@router.post("/quote")
async def generate_quote(body: AvailabilityQuery, property_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a detailed price quote for a specific property and dates."""
    ci = date.fromisoformat(body.check_in)
    co = date.fromisoformat(body.check_out)
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise HTTPException(404, "Property not found")

    if ci >= co:
        raise HTTPException(400, "Check-out must be after check-in")
    if (co - ci).days > 30:
        raise HTTPException(400, "Maximum stay is 30 nights")

    try:
        breakdown = await calculate_locked_fast_quote_breakdown(
            db,
            prop.id,
            ci,
            co,
            body.guests,
            adults=body.adults,
            children=body.children,
            pets=body.pets,
        )
        await db.commit()
    except FastQuoteError as exc:
        await db.rollback()
        raise HTTPException(exc.http_status, exc.message) from exc
    except Exception:
        await db.rollback()
        raise

    nights = (co - ci).days
    nightly_rate = float((breakdown.rent / nights).quantize(Decimal("0.01"))) if nights else 0.0

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "check_in": body.check_in,
        "check_out": body.check_out,
        "nights": nights,
        "guests": body.guests,
        "pricing_source": breakdown.pricing_source,
        "breakdown": {
            "nightly_rate": nightly_rate,
            "subtotal": float(breakdown.rent),
            "cleaning_fee": float(breakdown.cleaning),
            "admin_fee": float(breakdown.admin_fee),
            "pet_fee": float(breakdown.pet_fee),
            "service_fee": 0,
            "tax": float(breakdown.taxes),
            "total": float(breakdown.total),
            "line_items": [dict(row) for row in breakdown.line_items],
            "nightly_breakdown": [],
        },
    }


@router.post("/signed-quote")
async def issue_signed_quote(
    body: AvailabilityQuery,
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return a cryptographically sealed quote for checkout when signing key is configured."""
    ci = date.fromisoformat(body.check_in)
    co = date.fromisoformat(body.check_out)
    prop = await db.get(Property, property_id)
    if not prop or not prop.is_active:
        raise HTTPException(404, "Property not found")

    if ci >= co:
        raise HTTPException(400, "Check-out must be after check-in")
    if (co - ci).days > 30:
        raise HTTPException(400, "Maximum stay is 30 nights")

    try:
        payload = await issue_signed_checkout_quote(
            db,
            prop.id,
            ci,
            co,
            body.guests,
            adults=body.adults,
            children=body.children,
            pets=body.pets,
            signing_secret=settings.sovereign_quote_signing_key,
        )
    except FastQuoteError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    except ValueError as exc:
        if str(exc) == "sovereign_quote_internal_total_mismatch":
            raise HTTPException(500, "Quote computation error") from exc
        raise HTTPException(422, str(exc)) from exc

    return payload


@router.post("/book")
async def create_booking(body: BookingRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Create a checkout hold and Stripe PaymentIntent. Dates are locked for TTL.
    Call POST /confirm-hold after client-side payment succeeds (webhook also finalizes).
    """
    ci = date.fromisoformat(body.check_in)
    co = date.fromisoformat(body.check_out)
    prop = await db.get(Property, body.property_id)
    if not prop or not prop.is_active:
        raise HTTPException(404, "Property not found")

    if ci >= co:
        raise HTTPException(400, "Check-out must be after check-in")
    if (co - ci).days > 30:
        raise HTTPException(400, "Maximum stay is 30 nights")

    session_id = (
        body.session_id
        or request.headers.get("x-session-id")
        or request.cookies.get("fortress_session")
        or request.cookies.get("fortress_checkout_session")
        or f"checkout-{uuid4()}"
    )

    try:
        payload = await create_checkout_hold(
            db,
            property_id=prop.id,
            check_in=ci,
            check_out=co,
            session_id=session_id,
            num_guests=body.num_guests,
            guest_first_name=body.guest_first_name,
            guest_last_name=body.guest_last_name,
            guest_email=body.guest_email,
            guest_phone=body.guest_phone,
            special_requests=body.special_requests,
            signed_quote=body.signed_quote,
            pets=body.pets,
            adults=body.adults,
            children=body.children,
        )
    except BookingHoldError as exc:
        raise HTTPException(exc.status_code, exc.args[0]) from exc

    if body.intent_session_id:
        hold_uuid = UUID(payload["hold_id"])
        hold_row = await db.get(ReservationHold, hold_uuid)
        if hold_row is not None:
            await record_hold_intent_bridge(
                db,
                intent_session_id=body.intent_session_id,
                guest_id=hold_row.guest_id,
                hold_id=hold_uuid,
                property_slug=prop.slug,
            )

    await record_audit_event(
        action="reservation.checkout_hold.create",
        resource_type="reservation_hold",
        resource_id=payload["hold_id"],
        purpose="direct_booking",
        tool_name="direct_booking_create_hold",
        redaction_status="contains_pii_local_only",
        model_route="tool",
        outcome="success",
        metadata_json={
            "property_id": str(prop.id),
            "guest_phone": body.guest_phone[-4:],
            "check_in": body.check_in,
            "check_out": body.check_out,
            "total_amount": str(payload.get("total_amount")),
        },
    )

    return {
        "hold_id": payload["hold_id"],
        "expires_at": payload["expires_at"],
        "total_amount": payload["total_amount"],
        "payment": payload["payment"],
        "reservation_id": None,
        "confirmation_code": None,
    }


@router.post("/confirm-hold")
async def confirm_hold(body: ConfirmHoldRequest, db: AsyncSession = Depends(get_db)):
    """Finalize a hold into a confirmed reservation after Stripe reports success."""
    try:
        hold_uuid = UUID(body.hold_id)
    except ValueError as exc:
        raise HTTPException(422, "Invalid hold_id") from exc

    try:
        outcome = await finalize_hold_as_reservation(db, hold_uuid)
    except BookingHoldError as exc:
        raise HTTPException(exc.status_code, exc.args[0]) from exc

    await db.commit()
    reservation = outcome.reservation
    return {
        "reservation_id": str(reservation.id),
        "confirmation_code": reservation.confirmation_code,
        "total_amount": float(reservation.total_amount or 0),
        "already_processed": outcome.already_finalized,
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
        "sovereign_quote_signing_required": settings.sovereign_quote_signing_enabled,
    }


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify Stripe events; finalize checkout holds on payment_intent.succeeded."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = await stripe_payments.handle_webhook(payload, sig)
    except Exception as exc:
        raise HTTPException(400, "Webhook verification failed") from exc

    event_type = event.get("type", "")
    if event_type == "payment_intent.succeeded":
        obj = event.get("data", {}).get("object") or {}
        meta = obj.get("metadata") or {}
        if meta.get("source") == "direct_booking_hold":
            pi_id = str(obj.get("id") or "").strip()
            meta_hold = meta.get("hold_id") or meta.get("reservation_hold_id")
            meta_hold = str(meta_hold).strip() if meta_hold else None
            if pi_id:
                try:
                    await convert_hold_to_reservation(
                        pi_id,
                        db,
                        metadata_hold_id=meta_hold,
                    )
                except BookingHoldError as exc:
                    raise HTTPException(exc.status_code, exc.args[0]) from exc

    return {"status": "ok", "event_type": event_type}
