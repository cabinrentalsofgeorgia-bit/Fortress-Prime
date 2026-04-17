"""
Reservations API - Booking lifecycle management
BETTER THAN: All competitors (automated messaging triggers, lifecycle tracking)
"""
import structlog
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, asc, desc as sa_desc, case, literal
from pydantic import BaseModel

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.core.websocket import emit_reservation_update
from backend.models import Reservation, Guest, Property, Message, WorkOrder, DamageClaim, RentalAgreement
from backend.schemas.folio import (
    FolioGuest,
    FolioStay,
    FolioFinancials,
    FolioSecurityDeposit,
    FolioMessage,
    FolioWorkOrder,
    FolioDamageClaim,
    FolioAgreement,
    FolioLifecycle,
    ReservationFolio,
)

_log = structlog.get_logger("reservations")

SORTABLE_COLUMNS = {
    "check_in_date": Reservation.check_in_date,
    "check_out_date": Reservation.check_out_date,
    "total_amount": Reservation.total_amount,
    "status": Reservation.status,
    "created_at": Reservation.created_at,
    "confirmation_code": Reservation.confirmation_code,
    "num_guests": Reservation.num_guests,
}

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


class ReservationResponse(BaseModel):
    """Reservation response with guest/property names"""
    id: UUID
    confirmation_code: str
    guest_id: UUID
    property_id: UUID
    check_in_date: date
    check_out_date: date
    num_guests: int
    status: str
    access_code: Optional[str]
    booking_source: Optional[str]
    total_amount: Optional[float]
    is_current: bool
    is_arriving_today: bool
    is_departing_today: bool
    nights: int
    created_at: datetime
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    guest_email: Optional[str] = None
    property_name: Optional[str] = None

    class Config:
        from_attributes = True


def _et_today():
    import pytz
    return datetime.now(pytz.timezone("America/New_York")).date()


def _normalize_reservation_status(raw: object) -> str:
    """Lowercase + underscores so UI/TapeChart match Streamline casing (e.g. Confirmed → confirmed)."""
    s = str(raw or "").strip().lower().replace(" ", "_")
    return s if s else "confirmed"


def _enrich_reservation(r: Reservation, guest: Guest = None, prop: Property = None) -> dict:
    data = {c.name: getattr(r, c.name) for c in r.__table__.columns}
    data["status"] = _normalize_reservation_status(data.get("status"))
    today = _et_today()
    data["is_current"] = bool(r.check_in_date and r.check_out_date and r.check_in_date <= today <= r.check_out_date)
    data["is_arriving_today"] = r.check_in_date == today
    data["is_departing_today"] = r.check_out_date == today
    data["nights"] = (r.check_out_date - r.check_in_date).days if r.check_out_date and r.check_in_date else 0
    if guest:
        first = (guest.first_name or "").strip()
        last = (guest.last_name or "").strip()
        full_name = f"{first} {last}".strip()
        data["guest_name"] = full_name or None
        data["guest_phone"] = guest.phone_number
        data["guest_email"] = guest.email
    if prop:
        data["property_name"] = prop.name
    return data


@router.get("/")
async def list_reservations(
    status: Optional[str] = Query(None),
    property_id: Optional[UUID] = Query(None),
    check_in_after: Optional[date] = Query(None),
    check_in_before: Optional[date] = Query(None),
    search: Optional[str] = Query(None, description="Search by guest name, email, phone, or confirmation code"),
    sort_by: str = Query("check_in_date", description="Column to sort by"),
    order: str = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(500, le=2000),
    db: AsyncSession = Depends(get_db)
):
    """List reservations with guest/property names, dynamic sorting, and optional search."""
    query = select(Reservation, Guest, Property).join(
        Guest, Reservation.guest_id == Guest.id
    ).join(
        Property, Reservation.property_id == Property.id
    )

    if status:
        query = query.where(Reservation.status == status)
    if property_id:
        query = query.where(Reservation.property_id == property_id)
    if check_in_after:
        query = query.where(Reservation.check_in_date >= check_in_after)
    if check_in_before:
        query = query.where(Reservation.check_in_date <= check_in_before)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Guest.first_name.ilike(term),
                Guest.last_name.ilike(term),
                Guest.email.ilike(term),
                Guest.phone_number.ilike(term),
                Reservation.confirmation_code.ilike(term),
                func.concat(Guest.first_name, ' ', Guest.last_name).ilike(term),
            )
        )

    import pytz
    from datetime import timedelta as _td
    et_today = datetime.now(pytz.timezone("America/New_York")).date()
    et_tomorrow = et_today + _td(days=1)

    # Physical Reality Sort — always prepended to push real occupants to top
    physical_priority = case(
        (
            (Reservation.check_in_date <= et_today)
            & (Reservation.check_out_date >= et_today)
            & (Reservation.status == "checked_in"),
            literal(0),
        ),
        (
            (Reservation.check_out_date < et_today)
            & (Reservation.status == "checked_in"),
            literal(1),
        ),
        (
            (Reservation.check_in_date >= et_today)
            & (Reservation.check_in_date <= et_tomorrow)
            & (Reservation.status == "confirmed"),
            literal(2),
        ),
        (
            (Reservation.status == "checked_in")
            & (Reservation.check_in_date > et_today),
            literal(8),
        ),
        else_=literal(5),
    )

    sort_col = SORTABLE_COLUMNS.get(sort_by, Reservation.check_in_date)
    sort_dir = asc if order.lower() == "asc" else sa_desc
    query = query.order_by(physical_priority.asc(), sort_dir(sort_col)).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    return [_enrich_reservation(r, g, p) for r, g, p in rows]


@router.get("/arriving/today")
async def reservations_arriving_today(db: AsyncSession = Depends(get_db)):
    """Get reservations with check-in today"""
    today = _et_today()
    result = await db.execute(
        select(Reservation, Guest, Property)
        .join(Guest, Reservation.guest_id == Guest.id)
        .join(Property, Reservation.property_id == Property.id)
        .where(Reservation.check_in_date == today, Reservation.status.in_(["confirmed", "checked_in"]))
    )
    return [_enrich_reservation(r, g, p) for r, g, p in result.all()]


@router.get("/departing/today")
async def reservations_departing_today(db: AsyncSession = Depends(get_db)):
    """Get reservations with check-out today"""
    today = _et_today()
    result = await db.execute(
        select(Reservation, Guest, Property)
        .join(Guest, Reservation.guest_id == Guest.id)
        .join(Property, Reservation.property_id == Property.id)
        .where(Reservation.check_out_date == today, Reservation.status.in_(["confirmed", "checked_in", "checked_out", "no_show"]))
    )
    return [_enrich_reservation(r, g, p) for r, g, p in result.all()]


@router.get("/{reservation_id}")
async def get_reservation(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get reservation by ID with guest/property names"""
    result = await db.execute(
        select(Reservation, Guest, Property)
        .join(Guest, Reservation.guest_id == Guest.id)
        .join(Property, Reservation.property_id == Property.id)
        .where(Reservation.id == reservation_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Reservation not found")
    r, g, p = row
    return _enrich_reservation(r, g, p)


class ReservationUpdate(BaseModel):
    """Fields that can be patched on a reservation"""
    status: Optional[str] = None
    internal_notes: Optional[str] = None
    special_requests: Optional[str] = None
    access_code: Optional[str] = None


@router.patch("/{reservation_id}")
async def update_reservation(
    reservation_id: UUID,
    body: ReservationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a reservation's status, notes, special requests, or access code."""
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if body.status is not None:
        reservation.status = body.status
    if body.internal_notes is not None:
        reservation.internal_notes = body.internal_notes
    if body.special_requests is not None:
        reservation.special_requests = body.special_requests
    if body.access_code is not None:
        reservation.access_code = body.access_code

    reservation.updated_at = datetime.utcnow()

    guest = await db.get(Guest, reservation.guest_id)
    prop = await db.get(Property, reservation.property_id)
    enriched = _enrich_reservation(reservation, guest, prop)

    try:
        await emit_reservation_update({
            "id": str(reservation.id),
            "confirmation_code": reservation.confirmation_code,
            "status": reservation.status,
            "property_name": prop.name if prop else None,
            "guest_name": enriched.get("guest_name"),
        })
    except Exception:
        pass

    return enriched


@router.get("/{reservation_id}/full")
async def get_reservation_full(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Reservation hub — returns everything about a stay in one call:
    reservation, guest, property, messages, work orders, damage claims, agreement.
    Follows the Streamline/Track HS pattern of one-screen-per-reservation.
    """
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")

    guest = await db.get(Guest, reservation.guest_id)
    prop = await db.get(Property, reservation.property_id)

    msg_result = await db.execute(
        select(Message)
        .where(Message.guest_id == reservation.guest_id)
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    messages = msg_result.scalars().all()

    wo_result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.reservation_id == reservation_id)
        .order_by(WorkOrder.created_at.desc())
    )
    work_orders = wo_result.scalars().all()

    dc_result = await db.execute(
        select(DamageClaim)
        .where(DamageClaim.reservation_id == reservation_id)
        .order_by(DamageClaim.created_at.desc())
    )
    damage_claims = dc_result.scalars().all()

    ra_result = await db.execute(
        select(RentalAgreement)
        .where(RentalAgreement.reservation_id == reservation_id)
        .order_by(RentalAgreement.created_at.desc())
        .limit(1)
    )
    agreement = ra_result.scalars().first()

    def _ser_date(d):
        return str(d) if d else None

    return {
        "reservation": {
            "id": str(reservation.id),
            "confirmation_code": reservation.confirmation_code,
            "check_in_date": _ser_date(reservation.check_in_date),
            "check_out_date": _ser_date(reservation.check_out_date),
            "num_guests": reservation.num_guests,
            "status": reservation.status,
            "access_code": reservation.access_code,
            "booking_source": reservation.booking_source,
            "total_amount": float(reservation.total_amount) if reservation.total_amount else None,
            "paid_amount": float(reservation.paid_amount) if reservation.paid_amount else None,
            "balance_due": float(reservation.balance_due) if reservation.balance_due else None,
            "nightly_rate": float(reservation.nightly_rate) if reservation.nightly_rate else None,
            "cleaning_fee": float(reservation.cleaning_fee) if reservation.cleaning_fee else None,
            "pet_fee": float(reservation.pet_fee) if reservation.pet_fee else None,
            "damage_waiver_fee": float(reservation.damage_waiver_fee) if reservation.damage_waiver_fee else None,
            "service_fee": float(reservation.service_fee) if reservation.service_fee else None,
            "tax_amount": float(reservation.tax_amount) if reservation.tax_amount else None,
            "nights_count": reservation.nights_count,
            "price_breakdown": reservation.price_breakdown,
            "nights": (reservation.check_out_date - reservation.check_in_date).days if reservation.check_out_date and reservation.check_in_date else 0,
            "pre_arrival_sent": reservation.pre_arrival_sent,
            "access_info_sent": reservation.access_info_sent,
            "mid_stay_checkin_sent": reservation.mid_stay_checkin_sent,
            "checkout_reminder_sent": reservation.checkout_reminder_sent,
            "post_stay_followup_sent": reservation.post_stay_followup_sent,
            "internal_notes": reservation.internal_notes,
            "streamline_notes": reservation.streamline_notes,
            "special_requests": reservation.special_requests,
            "created_at": _ser_date(reservation.created_at),
        },
        "guest": {
            "id": str(guest.id),
            "first_name": guest.first_name,
            "last_name": guest.last_name,
            "email": guest.email,
            "phone_number": guest.phone_number,
            "vip_status": getattr(guest, "vip_status", None),
        } if guest else None,
        "property": {
            "id": str(prop.id),
            "name": prop.name,
            "address": prop.address,
            "bedrooms": prop.bedrooms,
            "bathrooms": float(prop.bathrooms) if prop.bathrooms else None,
            "max_guests": prop.max_guests,
            "wifi_ssid": prop.wifi_ssid,
            "wifi_password": prop.wifi_password,
        } if prop else None,
        "messages": [
            {
                "id": str(m.id),
                "direction": m.direction,
                "body": m.body,
                "status": m.status,
                "phone_from": m.phone_from,
                "phone_to": m.phone_to,
                "is_auto_response": m.is_auto_response,
                "intent": m.intent,
                "sentiment": getattr(m, 'sentiment', None),
                "created_at": _ser_date(m.created_at),
            }
            for m in messages
        ],
        "work_orders": [
            {
                "id": str(wo.id),
                "ticket_number": wo.ticket_number,
                "title": wo.title,
                "category": wo.category,
                "priority": wo.priority,
                "status": wo.status,
                "description": wo.description,
                "created_at": _ser_date(wo.created_at),
            }
            for wo in work_orders
        ],
        "damage_claims": [
            {
                "id": str(dc.id),
                "claim_number": dc.claim_number,
                "damage_description": dc.damage_description,
                "policy_violations": dc.policy_violations,
                "damage_areas": dc.damage_areas,
                "estimated_cost": float(dc.estimated_cost) if dc.estimated_cost else None,
                "status": dc.status,
                "legal_draft": dc.legal_draft,
                "legal_draft_model": dc.legal_draft_model,
                "final_response": dc.final_response,
                "inspection_date": _ser_date(dc.inspection_date),
                "created_at": _ser_date(dc.created_at),
            }
            for dc in damage_claims
        ],
        "rental_agreement": {
            "id": str(agreement.id),
            "status": agreement.status,
            "signed_at": _ser_date(agreement.signed_at),
            "signer_name": agreement.signer_name,
            "agreement_type": agreement.agreement_type,
            "agreement_url": agreement.agreement_url,
            "pdf_url": agreement.pdf_url,
            "has_content": bool(agreement.rendered_content),
        } if agreement else None,
        "lifecycle": {
            "pre_arrival_sent": reservation.pre_arrival_sent,
            "access_info_sent": reservation.access_info_sent,
            "mid_stay_checkin_sent": reservation.mid_stay_checkin_sent,
            "checkout_reminder_sent": reservation.checkout_reminder_sent,
            "post_stay_followup_sent": reservation.post_stay_followup_sent,
        },
    }


# ── Security Deposit Toggle ──────────────────────────────────────


class DepositToggleResponse(BaseModel):
    reservation_id: str
    security_deposit_required: bool
    security_deposit_amount: float
    security_deposit_status: str
    system_flag: Optional[str] = None


@router.post("/{reservation_id}/toggle-deposit")
async def toggle_security_deposit(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Flip the security_deposit_required flag on a reservation.
    Staff uses this to flag sketchy bookings for a $500 hold.
    The actual Stripe auth is scheduled by a cron at T-24h.
    """
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")

    new_val = not bool(reservation.security_deposit_required)
    reservation.security_deposit_required = new_val

    if not new_val:
        if reservation.security_deposit_status == "none":
            pass
        elif reservation.security_deposit_status == "scheduled":
            reservation.security_deposit_status = "none"

    reservation.security_deposit_updated_at = datetime.utcnow()
    await db.commit()

    deposit_status = str(reservation.security_deposit_status or "none")
    flag = "DEPOSIT PENDING" if new_val and deposit_status == "none" else None

    _log.info(
        "security_deposit_toggled",
        reservation_id=str(reservation_id),
        required=new_val,
        status=deposit_status,
    )

    return DepositToggleResponse(
        reservation_id=str(reservation_id),
        security_deposit_required=new_val,
        security_deposit_amount=float(reservation.security_deposit_amount or 500.00),
        security_deposit_status=deposit_status,
        system_flag=flag,
    )


# ── Security Deposit Hold / Capture / Release ────────────────────

class DepositActionResponse(BaseModel):
    reservation_id: str
    security_deposit_status: str
    stripe_pi: Optional[str] = None
    amount: Optional[float] = None


@router.post("/{reservation_id}/deposit/initiate")
async def initiate_security_deposit(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Place a manual-capture PaymentIntent authorization hold for the security deposit.
    Transitions status: none/pending/scheduled → authorized.
    Requires the guest to have a stripe_customer_id (created at booking).
    """
    from backend.integrations.stripe_payments import StripePayments
    from backend.models import Guest

    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    if not reservation.security_deposit_required:
        raise HTTPException(400, "Security deposit is not required for this reservation")
    if reservation.security_deposit_status == "authorized":
        raise HTTPException(400, "Deposit hold already active")
    if reservation.security_deposit_status in ("captured", "released"):
        raise HTTPException(400, f"Deposit already finalized: {reservation.security_deposit_status}")

    guest = await db.get(Guest, reservation.guest_id)
    if not guest:
        raise HTTPException(404, "Guest not found")

    stripe = StripePayments()
    customer_id = await stripe.get_or_create_customer(
        email=reservation.guest_email or guest.email,
        name=reservation.guest_name or f"{guest.first_name} {guest.last_name}",
        stripe_customer_id=guest.stripe_customer_id or None,
    )

    # Save back if newly created
    if not guest.stripe_customer_id:
        guest.stripe_customer_id = customer_id

    amount_cents = int(float(reservation.security_deposit_amount or 500.00) * 100)
    result = await stripe.create_deposit_intent(
        customer_id=customer_id,
        amount_cents=amount_cents,
        reservation_id=str(reservation_id),
        description=f"Security deposit — {reservation.confirmation_code}",
    )

    reservation.security_deposit_stripe_pi = result["payment_intent_id"]
    reservation.security_deposit_status = "authorized"
    reservation.security_deposit_updated_at = datetime.utcnow()
    await db.commit()

    _log.info(
        "security_deposit_initiated",
        reservation_id=str(reservation_id),
        intent_id=result["payment_intent_id"],
        amount_cents=amount_cents,
    )
    return DepositActionResponse(
        reservation_id=str(reservation_id),
        security_deposit_status="authorized",
        stripe_pi=result["payment_intent_id"],
        amount=float(reservation.security_deposit_amount or 500.00),
    )


@router.post("/{reservation_id}/deposit/capture")
async def capture_security_deposit(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Capture the authorized deposit hold — charges the guest's card.
    Transitions status: authorized → captured.
    """
    from backend.integrations.stripe_payments import StripePayments

    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    if reservation.security_deposit_status != "authorized":
        raise HTTPException(400, f"Cannot capture deposit in status: {reservation.security_deposit_status}")
    if not reservation.security_deposit_stripe_pi:
        raise HTTPException(400, "No active deposit PaymentIntent found")

    stripe = StripePayments()
    result = await stripe.capture_deposit_intent(reservation.security_deposit_stripe_pi)

    reservation.security_deposit_status = "captured"
    reservation.security_deposit_updated_at = datetime.utcnow()
    await db.commit()

    _log.info(
        "security_deposit_captured",
        reservation_id=str(reservation_id),
        intent_id=reservation.security_deposit_stripe_pi,
        amount_captured=result.get("amount_captured"),
    )
    return DepositActionResponse(
        reservation_id=str(reservation_id),
        security_deposit_status="captured",
        stripe_pi=reservation.security_deposit_stripe_pi,
        amount=result.get("amount_captured", 0) / 100,
    )


@router.post("/{reservation_id}/deposit/release")
async def release_security_deposit(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel the authorized deposit hold — releases the hold with no charge.
    Transitions status: authorized → released.
    """
    from backend.integrations.stripe_payments import StripePayments

    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    if reservation.security_deposit_status != "authorized":
        raise HTTPException(400, f"Cannot release deposit in status: {reservation.security_deposit_status}")
    if not reservation.security_deposit_stripe_pi:
        raise HTTPException(400, "No active deposit PaymentIntent found")

    stripe = StripePayments()
    await stripe.cancel_deposit_intent(reservation.security_deposit_stripe_pi)

    reservation.security_deposit_status = "released"
    reservation.security_deposit_updated_at = datetime.utcnow()
    await db.commit()

    _log.info(
        "security_deposit_released",
        reservation_id=str(reservation_id),
        intent_id=reservation.security_deposit_stripe_pi,
    )
    return DepositActionResponse(
        reservation_id=str(reservation_id),
        security_deposit_status="released",
        stripe_pi=reservation.security_deposit_stripe_pi,
    )


# ── Unified Folio Aggregator ─────────────────────────────────────


async def _aggregate_folio(
    reservation_id: UUID,
    db: AsyncSession,
) -> ReservationFolio:
    """
    Core aggregation logic — separated from the route handler so the
    backtesting script can call it directly without HTTP.
    Each data source is wrapped in its own try/except so a single
    failure (e.g. RueBaRue timeout) never kills the whole folio.
    """
    errors: List[str] = []

    # ── 1. Reservation + Guest + Property (local DB — authoritative) ──
    result = await db.execute(
        select(Reservation, Guest, Property)
        .join(Guest, Reservation.guest_id == Guest.id)
        .join(Property, Reservation.property_id == Property.id)
        .where(Reservation.id == reservation_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Reservation not found")

    res, guest, prop = row

    def _s(v: Any) -> str:
        return str(v) if v is not None else ""

    def _f(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return 0.0

    def _sd(v: Any) -> Optional[str]:
        return str(v) if v else None

    folio_guest = FolioGuest(
        id=_s(guest.id),
        first_name=_s(guest.first_name),
        last_name=_s(guest.last_name),
        email=_s(guest.email),
        phone_number=_s(guest.phone_number),
        address_line1=_s(getattr(guest, "address_line1", "")),
        city=_s(getattr(guest, "city", "")),
        state=_s(getattr(guest, "state", "")),
        postal_code=_s(getattr(guest, "postal_code", "")),
        country=_s(getattr(guest, "country", "")),
        loyalty_tier=_s(getattr(guest, "loyalty_tier", "")),
        lifetime_stays=getattr(guest, "lifetime_stays", 0) or 0,
        lifetime_revenue=_f(getattr(guest, "lifetime_revenue", 0)),
        vip_status=getattr(guest, "vip_status", None),
        stripe_customer_id=getattr(guest, "stripe_customer_id", None),
    )

    folio_stay = FolioStay(
        id=_s(res.id),
        confirmation_code=_s(res.confirmation_code),
        property_id=_s(res.property_id),
        property_name=_s(prop.name),
        property_address=_s(getattr(prop, "address", "")),
        check_in_date=res.check_in_date,
        check_out_date=res.check_out_date,
        nights=(res.check_out_date - res.check_in_date).days if res.check_out_date and res.check_in_date else 0,
        num_guests=res.num_guests or 0,
        num_adults=res.num_adults,
        num_children=res.num_children,
        num_pets=res.num_pets or 0,
        status=_s(res.status),
        booking_source=_s(res.booking_source),
        access_code=res.access_code,
        access_code_type=_s(getattr(prop, "access_code_type", "")),
        access_code_location=_s(getattr(prop, "access_code_location", "")),
        wifi_ssid=_s(getattr(prop, "wifi_ssid", "")),
        wifi_password=_s(getattr(prop, "wifi_password", "")),
        special_requests=_s(res.special_requests),
        internal_notes=_s(res.internal_notes),
        streamline_notes=res.streamline_notes if isinstance(res.streamline_notes, list) else None,
    )

    folio_deposit = FolioSecurityDeposit(
        is_required=bool(getattr(res, "security_deposit_required", False)),
        amount_cents=getattr(res, "security_deposit_amount", 500.00),
        status=_s(getattr(res, "security_deposit_status", "none")) or "none",
        stripe_payment_intent=getattr(res, "security_deposit_stripe_pi", None),
        updated_at=_sd(getattr(res, "security_deposit_updated_at", None)),
    )

    folio_financials = FolioFinancials(
        total_amount_cents=res.total_amount,
        paid_amount_cents=res.paid_amount,
        balance_due_cents=res.balance_due,
        nightly_rate_cents=res.nightly_rate,
        cleaning_fee_cents=res.cleaning_fee,
        pet_fee_cents=res.pet_fee,
        damage_waiver_fee_cents=res.damage_waiver_fee,
        service_fee_cents=res.service_fee,
        tax_amount_cents=res.tax_amount,
        currency=_s(res.currency) or "USD",
        price_breakdown=res.price_breakdown if isinstance(res.price_breakdown, dict) else None,
        streamline_financial_detail=res.streamline_financial_detail if isinstance(res.streamline_financial_detail, dict) else None,
        security_deposit=folio_deposit,
    )

    folio_lifecycle = FolioLifecycle(
        pre_arrival_sent=bool(res.pre_arrival_sent),
        digital_guide_sent=bool(res.digital_guide_sent),
        access_info_sent=bool(res.access_info_sent),
        mid_stay_checkin_sent=bool(res.mid_stay_checkin_sent),
        checkout_reminder_sent=bool(res.checkout_reminder_sent),
        post_stay_followup_sent=bool(res.post_stay_followup_sent),
    )

    # ── 2. Messages (local DB — deduplicated) ──
    folio_messages: List[FolioMessage] = []
    try:
        msg_result = await db.execute(
            select(Message)
            .where(Message.reservation_id == reservation_id)
            .order_by(Message.created_at.asc())
            .limit(200)
        )
        raw_msgs = msg_result.scalars().all()

        # Collapse scheduler burst-fires: if same (body, direction, intent)
        # appears within 5 seconds, keep only the first occurrence.
        seen_keys: Dict[str, Any] = {}
        deduped: list = []
        for m in raw_msgs:
            body_prefix = (_s(m.body))[:120]
            dedup_key = f"{m.direction}|{m.intent or ''}|{body_prefix}"
            prev_ts = seen_keys.get(dedup_key)
            if prev_ts is not None and m.created_at is not None:
                delta = abs((m.created_at - prev_ts).total_seconds())
                if delta < 5.0:
                    continue
            if m.created_at is not None:
                seen_keys[dedup_key] = m.created_at
            deduped.append(m)

        for m in deduped:
            folio_messages.append(FolioMessage(
                id=_s(m.id),
                direction=_s(m.direction),
                body=_s(m.body),
                status=_s(m.status),
                phone_from=_s(m.phone_from),
                phone_to=_s(m.phone_to),
                channel=_s(getattr(m, "provider", "sms")),
                is_auto_response=bool(m.is_auto_response),
                intent=m.intent,
                sentiment=getattr(m, "sentiment", None),
                created_at=_sd(m.created_at),
            ))
    except Exception as e:
        _log.error("folio_messages_failed", reservation_id=str(reservation_id), error=str(e))
        errors.append(f"Messages: {e}")

    # ── 3. Work Orders (local DB) ──
    folio_work_orders: List[FolioWorkOrder] = []
    try:
        wo_result = await db.execute(
            select(WorkOrder)
            .where(WorkOrder.reservation_id == reservation_id)
            .order_by(WorkOrder.created_at.desc())
        )
        for wo in wo_result.scalars().all():
            folio_work_orders.append(FolioWorkOrder(
                id=_s(wo.id),
                ticket_number=getattr(wo, "ticket_number", None),
                title=_s(getattr(wo, "title", "")),
                category=getattr(wo, "category", None),
                priority=getattr(wo, "priority", None),
                status=_s(wo.status),
                description=_s(getattr(wo, "description", "")),
                created_at=_sd(wo.created_at),
            ))
    except Exception as e:
        _log.error("folio_work_orders_failed", reservation_id=str(reservation_id), error=str(e))
        errors.append(f"Work Orders: {e}")

    # ── 4. Damage Claims (local DB) ──
    folio_claims: List[FolioDamageClaim] = []
    try:
        dc_result = await db.execute(
            select(DamageClaim)
            .where(DamageClaim.reservation_id == reservation_id)
            .order_by(DamageClaim.created_at.desc())
        )
        for dc in dc_result.scalars().all():
            folio_claims.append(FolioDamageClaim(
                id=_s(dc.id),
                claim_number=getattr(dc, "claim_number", None),
                damage_description=_s(dc.damage_description),
                estimated_cost=_f(dc.estimated_cost),
                status=_s(dc.status),
                has_legal_draft=bool(dc.legal_draft),
                created_at=_sd(dc.created_at),
            ))
    except Exception as e:
        _log.error("folio_damage_claims_failed", reservation_id=str(reservation_id), error=str(e))
        errors.append(f"Damage Claims: {e}")

    # ── 5. Rental Agreement (local DB) ──
    folio_agreement: Optional[FolioAgreement] = None
    try:
        ra_result = await db.execute(
            select(RentalAgreement)
            .where(RentalAgreement.reservation_id == reservation_id)
            .order_by(RentalAgreement.created_at.desc())
            .limit(1)
        )
        agreement = ra_result.scalars().first()
        if agreement:
            folio_agreement = FolioAgreement(
                id=_s(agreement.id),
                status=_s(agreement.status),
                signed_at=_sd(agreement.signed_at),
                signer_name=_s(getattr(agreement, "signer_name", "")),
                agreement_type=_s(getattr(agreement, "agreement_type", "")),
                has_content=bool(getattr(agreement, "rendered_content", None)),
            )
    except Exception as e:
        _log.error("folio_agreement_failed", reservation_id=str(reservation_id), error=str(e))
        errors.append(f"Agreement: {e}")

    return ReservationFolio(
        guest=folio_guest,
        stay=folio_stay,
        financials=folio_financials,
        messages=folio_messages,
        work_orders=folio_work_orders,
        damage_claims=folio_claims,
        agreement=folio_agreement,
        lifecycle=folio_lifecycle,
        aggregation_errors=errors,
    )


@router.get("/{reservation_id}/folio")
async def get_reservation_folio(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Unified Folio Aggregator — returns a strict Pydantic-validated
    ReservationFolio combining Streamline (PMS), native payments,
    and communication data.  Each data source fails independently;
    the folio always returns with whatever data is available.
    """
    folio = await _aggregate_folio(reservation_id, db)
    return folio.model_dump()


@router.get("/{reservation_id}/agreement.pdf")
async def get_reservation_agreement_pdf(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and return the rental agreement PDF for a reservation.
    If a pre-generated file exists on disk, serve it.  Otherwise,
    generate on-the-fly from rendered_content via WeasyPrint.
    """
    import os
    from fastapi.responses import Response

    result = await db.execute(
        select(RentalAgreement, Reservation, Property)
        .join(Reservation, RentalAgreement.reservation_id == Reservation.id)
        .join(Property, Reservation.property_id == Property.id)
        .where(RentalAgreement.reservation_id == reservation_id)
        .order_by(RentalAgreement.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "No rental agreement found for this reservation")

    agreement, reservation, prop = row

    if agreement.pdf_url and os.path.exists(agreement.pdf_url):
        with open(agreement.pdf_url, "rb") as f:
            pdf_bytes = f.read()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="agreement-{reservation.confirmation_code}.pdf"',
            },
        )

    if not agreement.rendered_content:
        raise HTTPException(404, "Agreement has no content to render")

    try:
        from backend.services.pdf_generator import generate_agreement_pdf

        pdf_path = generate_agreement_pdf(
            agreement_id=str(agreement.id),
            rendered_content=agreement.rendered_content,
            signer_name=agreement.signer_name or "",
            signer_email=agreement.signer_email or "",
            signature_data=agreement.signature_data,
            signature_type=agreement.signature_type or "typed",
            initials_data=agreement.initials_data,
            initials_pages=agreement.initials_pages,
            signer_ip=agreement.signer_ip_address or "unknown",
            signer_user_agent=agreement.signer_user_agent or "unknown",
            signed_at=agreement.signed_at or agreement.created_at,
            agreement_type=agreement.agreement_type or "Rental Agreement",
            property_name=prop.name or "",
            confirmation_code=reservation.confirmation_code or "",
        )

        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(500, "PDF generation failed")

        agreement.pdf_url = pdf_path
        await db.commit()

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="agreement-{reservation.confirmation_code}.pdf"',
            },
        )
    except ImportError:
        raise HTTPException(
            503,
            "WeasyPrint not installed — cannot generate PDF. "
            "Install with: pip install weasyprint",
        )
    except HTTPException:
        raise
    except Exception as e:
        _log.error("agreement_pdf_failed", reservation_id=str(reservation_id), error=str(e))
        raise HTTPException(500, f"PDF generation error: {e}")
