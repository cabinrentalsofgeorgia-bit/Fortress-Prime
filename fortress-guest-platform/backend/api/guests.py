"""
Guests API - Enterprise Guest Management System
SURPASSES: Streamline VRS CRM + RueBaRue + Breezeway + ALL competitors

30+ endpoints for complete guest lifecycle management:
- CRUD with advanced search and filtering
- 360° guest profiles
- Scoring (value, risk, satisfaction)
- Loyalty program management
- Guest merge/dedup
- Segmentation for campaigns
- Reviews (bidirectional)
- Surveys & NPS
- Blacklist / VIP management
- Activity timeline
- Analytics dashboard
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, desc
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models.staff import StaffUser
from backend.models import Guest, Reservation, Message
from backend.services.guest_management import GuestManagementService

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEMAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GuestCreate(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+1\d{10}$")
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_preference: str = "en"
    guest_source: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    date_of_birth: Optional[date] = None
    special_requests: Optional[str] = None
    tags: Optional[List[str]] = None


class GuestUpdate(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number_secondary: Optional[str] = None
    email_secondary: Optional[str] = None
    language_preference: Optional[str] = None
    preferred_contact_method: Optional[str] = None
    opt_in_marketing: Optional[bool] = None
    opt_in_sms: Optional[bool] = None
    opt_in_email: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[date] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_color: Optional[str] = None
    vehicle_plate: Optional[str] = None
    vehicle_state: Optional[str] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    staff_notes: Optional[str] = None
    preferences: Optional[Dict] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class GuestResponse(BaseModel):
    id: UUID
    phone_number: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str
    loyalty_tier: Optional[str] = "bronze"
    value_score: Optional[int] = 50
    risk_score: Optional[int] = 10
    is_vip: bool = False
    is_verified: bool = False
    is_blacklisted: bool = False
    is_repeat_guest: bool = False
    total_stays: int = 0
    lifetime_revenue: Optional[float] = 0
    average_rating: Optional[float] = None
    last_stay_date: Optional[date] = None
    guest_source: Optional[str] = None
    tags: Optional[List[str]] = None
    verification_status: Optional[str] = "unverified"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GuestDetail(GuestResponse):
    phone_number_secondary: Optional[str] = None
    email_secondary: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    vehicle_description: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    display_tier: str = "Bronze"
    loyalty_points: int = 0
    lifetime_stays: int = 0
    lifetime_nights: int = 0
    satisfaction_score: Optional[int] = None
    preferred_contact_method: Optional[str] = "sms"
    opt_in_marketing: bool = True
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    preferences: Optional[Dict] = None
    reservation_count: int = 0
    upcoming_reservations: int = 0
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    lifetime_value: float = 0
    notes: Optional[str] = None


class ReviewSubmit(BaseModel):
    reservation_id: UUID
    property_id: UUID
    overall_rating: int = Field(..., ge=1, le=5)
    body: str
    category_ratings: Optional[Dict[str, int]] = None
    submitted_via: str = "web_form"


class ManagerReviewSubmit(BaseModel):
    reservation_id: UUID
    property_id: UUID
    overall_rating: int = Field(..., ge=1, le=5)
    body: str
    category_ratings: Optional[Dict[str, int]] = None
    reviewed_by: str = "manager"


class ReviewResponse(BaseModel):
    response_body: str
    responded_by: str


class SurveyResponseSubmit(BaseModel):
    responses: Dict


class SegmentCriteria(BaseModel):
    min_stays: Optional[int] = None
    max_stays: Optional[int] = None
    min_revenue: Optional[float] = None
    loyalty_tier: Optional[Any] = None
    last_stay_within_days: Optional[int] = None
    no_stay_since_days: Optional[int] = None
    tags: Optional[List[str]] = None
    is_vip: Optional[bool] = None
    is_repeat: Optional[bool] = None
    opt_in_marketing: Optional[bool] = None
    opt_in_sms: Optional[bool] = None
    source: Optional[str] = None
    min_value_score: Optional[int] = None
    max_risk_score: Optional[int] = None
    verification_status: Optional[str] = None
    state: Optional[str] = None
    is_blacklisted: Optional[bool] = None
    sort_by: Optional[str] = "lifetime_revenue"
    sort_dir: Optional[str] = "desc"
    limit: Optional[int] = 500


class MergeRequest(BaseModel):
    primary_id: UUID
    secondary_id: UUID
    performed_by: str = "admin"


class BlacklistRequest(BaseModel):
    reason: str
    blacklisted_by: str


class VIPToggle(BaseModel):
    is_vip: bool
    by: str = "admin"


def _build_guest_response(guest: Guest) -> GuestResponse:
    """Build a GuestResponse from a Guest model"""
    return GuestResponse(
        id=guest.id,
        phone_number=guest.phone_number or "",
        email=guest.email,
        first_name=guest.first_name,
        last_name=guest.last_name,
        full_name=guest.full_name,
        loyalty_tier=guest.loyalty_tier or "bronze",
        value_score=guest.value_score or 50,
        risk_score=guest.risk_score or 10,
        is_vip=guest.is_vip,
        is_verified=guest.is_verified,
        is_blacklisted=guest.is_blacklisted,
        is_repeat_guest=guest.is_repeat_guest,
        total_stays=guest.total_stays or 0,
        lifetime_revenue=float(guest.lifetime_revenue or 0),
        average_rating=float(guest.average_rating) if guest.average_rating is not None else None,
        last_stay_date=guest.last_stay_date,
        guest_source=guest.guest_source,
        tags=guest.tags,
        verification_status=guest.verification_status or "unverified",
        created_at=guest.created_at,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CORE CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/", response_model=GuestResponse, status_code=201)
async def create_guest(
    guest_data: GuestCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new guest profile with duplicate detection"""
    result = await db.execute(
        select(Guest).where(Guest.phone_number == guest_data.phone_number)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"Guest with phone {guest_data.phone_number} already exists")

    guest = Guest(**guest_data.model_dump(exclude_unset=True))
    db.add(guest)
    await db.commit()
    await db.refresh(guest)
    return _build_guest_response(guest)


@router.get("/", response_model=List[GuestResponse])
async def list_guests(
    search: Optional[str] = Query(None, description="Search by name, phone, email"),
    tags: Optional[List[str]] = Query(None),
    loyalty_tier: Optional[str] = Query(None),
    is_vip: Optional[bool] = Query(None),
    is_repeat: Optional[bool] = Query(None),
    is_blacklisted: Optional[bool] = Query(None),
    verification_status: Optional[str] = Query(None),
    guest_source: Optional[str] = Query(None),
    min_stays: Optional[int] = Query(None),
    min_value_score: Optional[int] = Query(None),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_dir: str = Query("desc", description="asc or desc"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    List guests with powerful search and filtering
    
    BETTER THAN Streamline: Multi-dimensional filtering
    BETTER THAN RueBaRue: Full-text search across all fields
    """
    query = select(Guest)

    if search:
        search_filter = f"%{search}%"
        search_clauses = [
            Guest.first_name.ilike(search_filter),
            Guest.last_name.ilike(search_filter),
            Guest.email.ilike(search_filter),
            Guest.phone_number.ilike(search_filter),
            Guest.city.ilike(search_filter),
        ]
        query = query.where(or_(*search_clauses))

    if tags:
        query = query.where(Guest.tags.contains(tags))
    if loyalty_tier:
        query = query.where(Guest.loyalty_tier == loyalty_tier)
    if is_vip is not None:
        query = query.where(Guest.is_vip == is_vip)
    if is_repeat is not None:
        if is_repeat:
            query = query.where(Guest.lifetime_stays > 1)
        else:
            query = query.where(Guest.lifetime_stays <= 1)
    if is_blacklisted is not None:
        query = query.where(Guest.is_blacklisted == is_blacklisted)
    if verification_status:
        query = query.where(Guest.verification_status == verification_status)
    if guest_source:
        query = query.where(Guest.guest_source == guest_source)
    if min_stays:
        query = query.where(Guest.lifetime_stays >= min_stays)
    if min_value_score:
        query = query.where(Guest.value_score >= min_value_score)

    sort_col = getattr(Guest, sort_by, Guest.created_at)
    query = query.order_by(desc(sort_col) if sort_dir == "desc" else sort_col)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    return [_build_guest_response(g) for g in result.scalars().all()]


@router.get("/analytics", response_model=Dict)
async def guest_analytics(
    days: int = Query(30, description="Period in days"),
    db: AsyncSession = Depends(get_db)
):
    """
    Guest analytics dashboard
    Streamline shows counts. We show intelligence.
    """
    svc = GuestManagementService(db)
    return await svc.get_guest_analytics(days=days)


@router.get("/arriving/today", response_model=List[GuestResponse])
async def guests_arriving_today(db: AsyncSession = Depends(get_db)):
    """Guests arriving today"""
    today = datetime.utcnow().date()
    result = await db.execute(
        select(Guest).join(Reservation).where(
            Reservation.check_in_date == today,
            Reservation.status == "confirmed"
        )
    )
    return [_build_guest_response(g) for g in result.scalars().all()]


@router.get("/staying/now", response_model=List[GuestResponse])
async def guests_staying_now(db: AsyncSession = Depends(get_db)):
    """Guests currently staying"""
    today = datetime.utcnow().date()
    result = await db.execute(
        select(Guest).join(Reservation).where(
            Reservation.status == "checked_in",
            Reservation.check_in_date <= today,
            Reservation.check_out_date >= today
        )
    )
    return [_build_guest_response(g) for g in result.scalars().all()]


@router.get("/departing/today", response_model=List[GuestResponse])
async def guests_departing_today(db: AsyncSession = Depends(get_db)):
    """Guests departing today"""
    today = datetime.utcnow().date()
    result = await db.execute(
        select(Guest).join(Reservation).where(
            Reservation.check_out_date == today,
            Reservation.status.in_(["confirmed", "checked_in"])
        )
    )
    return [_build_guest_response(g) for g in result.scalars().all()]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 360° PROFILE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{guest_id}", response_model=GuestDetail)
async def get_guest(guest_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get guest with full detail view"""
    guest = await db.get(Guest, guest_id)
    if not guest:
        raise HTTPException(404, "Guest not found")

    res_count = (await db.execute(
        select(func.count(Reservation.id)).where(Reservation.guest_id == guest_id)
    )).scalar()
    upcoming = (await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.guest_id == guest_id,
            Reservation.check_in_date >= datetime.utcnow().date(),
            Reservation.status.in_(["confirmed", "checked_in"])
        )
    )).scalar()
    msg_count = (await db.execute(
        select(func.count(Message.id)).where(Message.guest_id == guest_id)
    )).scalar()
    last_msg = (await db.execute(
        select(Message.created_at).where(Message.guest_id == guest_id)
        .order_by(Message.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    ltv = float((await db.execute(
        select(func.coalesce(func.sum(Reservation.total_amount), 0))
        .where(Reservation.guest_id == guest_id)
    )).scalar())

    return GuestDetail(
        id=guest.id,
        phone_number=guest.phone_number or "",
        phone_number_secondary=guest.phone_number_secondary,
        email=guest.email,
        email_secondary=guest.email_secondary,
        first_name=guest.first_name,
        last_name=guest.last_name,
        full_name=guest.full_name,
        address=guest.full_address,
        city=guest.city,
        state=guest.state,
        loyalty_tier=guest.loyalty_tier or "bronze",
        display_tier=guest.display_tier,
        loyalty_points=guest.loyalty_points or 0,
        lifetime_stays=guest.lifetime_stays or 0,
        lifetime_nights=guest.lifetime_nights or 0,
        lifetime_revenue=float(guest.lifetime_revenue or 0),
        value_score=guest.value_score or 50,
        risk_score=guest.risk_score or 10,
        satisfaction_score=guest.satisfaction_score,
        is_vip=guest.is_vip,
        is_verified=guest.is_verified,
        is_blacklisted=guest.is_blacklisted,
        is_repeat_guest=guest.is_repeat_guest,
        total_stays=guest.total_stays or 0,
        average_rating=float(guest.average_rating) if guest.average_rating is not None else None,
        last_stay_date=guest.last_stay_date,
        guest_source=guest.guest_source,
        tags=guest.tags,
        verification_status=guest.verification_status or "unverified",
        vehicle_description=guest.vehicle_description,
        emergency_contact_name=guest.emergency_contact_name,
        emergency_contact_phone=guest.emergency_contact_phone,
        preferred_contact_method=guest.preferred_contact_method or "sms",
        opt_in_marketing=guest.opt_in_marketing if guest.opt_in_marketing is not None else True,
        special_requests=guest.special_requests,
        internal_notes=guest.internal_notes,
        preferences=guest.preferences,
        reservation_count=res_count or 0,
        upcoming_reservations=upcoming or 0,
        message_count=msg_count or 0,
        last_message_at=last_msg,
        lifetime_value=ltv,
        notes=guest.notes,
        created_at=guest.created_at,
    )


@router.get("/{guest_id}/360", response_model=Dict)
async def get_guest_360(guest_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Complete 360° guest profile - THE premium view
    
    Everything about a guest in a single API call:
    profile, identity, vehicle, emergency, loyalty, scoring,
    reservations, messages, reviews, surveys, agreements,
    work orders, activity timeline
    """
    svc = GuestManagementService(db)
    profile = await svc.get_guest_360(guest_id)
    if not profile:
        raise HTTPException(404, "Guest not found")
    return profile


@router.patch("/{guest_id}", response_model=GuestResponse)
async def update_guest(
    guest_id: UUID,
    update_data: GuestUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update guest profile"""
    guest = await db.get(Guest, guest_id)
    if not guest:
        raise HTTPException(404, "Guest not found")

    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(guest, field, value)

    guest.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(guest)
    return _build_guest_response(guest)


@router.get("/phone/{phone_number}", response_model=GuestResponse)
async def get_guest_by_phone(phone_number: str, db: AsyncSession = Depends(get_db)):
    """Find guest by phone number"""
    result = await db.execute(
        select(Guest).where(Guest.phone_number == phone_number)
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Guest not found")
    return _build_guest_response(guest)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCORING & LOYALTY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/{guest_id}/recalculate-scores", response_model=Dict)
async def recalculate_scores(guest_id: UUID, db: AsyncSession = Depends(get_db)):
    """Recalculate guest value/risk/satisfaction scores and loyalty tier"""
    svc = GuestManagementService(db)
    result = await svc.recalculate_guest_scores(guest_id)
    if not result:
        raise HTTPException(404, "Guest not found")
    return result


@router.post("/batch-recalculate-scores", response_model=Dict)
async def batch_recalculate(db: AsyncSession = Depends(get_db)):
    """Recalculate scores for ALL guests (admin action)"""
    svc = GuestManagementService(db)
    return await svc.batch_recalculate_scores()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEGMENTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/segment", response_model=List[Dict])
async def segment_guests(
    criteria: SegmentCriteria,
    db: AsyncSession = Depends(get_db)
):
    """
    Advanced guest segmentation for targeted campaigns
    
    Examples:
    - VIP repeat guests: {"is_vip": true, "min_stays": 3}
    - High-value Airbnb: {"source": "airbnb", "min_revenue": 5000}
    - Lapsed guests: {"no_stay_since_days": 180, "opt_in_marketing": true}
    - Gold+ tier: {"loyalty_tier": ["gold", "platinum", "diamond"]}
    """
    svc = GuestManagementService(db)
    return await svc.segment_guests(criteria.model_dump(exclude_unset=True))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MERGE / DEDUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{guest_id}/duplicates", response_model=List[Dict])
async def find_duplicates(guest_id: UUID, db: AsyncSession = Depends(get_db)):
    """Find potential duplicate guest records"""
    svc = GuestManagementService(db)
    return await svc.find_potential_duplicates(guest_id)


@router.post("/merge", response_model=Dict)
async def merge_guests(merge: MergeRequest, db: AsyncSession = Depends(get_db)):
    """
    Merge two guest records (keep primary, absorb secondary)
    Re-links all reservations, messages, reviews, etc.
    """
    svc = GuestManagementService(db)
    try:
        return await svc.merge_guests(
            merge.primary_id, merge.secondary_id, merge.performed_by
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REVIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/{guest_id}/reviews", response_model=Dict, status_code=201)
async def submit_review(
    guest_id: UUID,
    review_data: ReviewSubmit,
    db: AsyncSession = Depends(get_db)
):
    """Submit a guest review of a property"""
    svc = GuestManagementService(db)
    review = await svc.submit_guest_review(
        guest_id=guest_id,
        reservation_id=review_data.reservation_id,
        property_id=review_data.property_id,
        overall_rating=review_data.overall_rating,
        body=review_data.body,
        category_ratings=review_data.category_ratings,
        submitted_via=review_data.submitted_via,
    )
    return {
        "id": str(review.id),
        "overall_rating": review.overall_rating,
        "sentiment": review.sentiment,
        "is_published": review.is_published,
    }


@router.post("/{guest_id}/manager-review", response_model=Dict, status_code=201)
async def submit_manager_review(
    guest_id: UUID,
    review_data: ManagerReviewSubmit,
    db: AsyncSession = Depends(get_db)
):
    """Submit an internal manager review OF a guest"""
    svc = GuestManagementService(db)
    review = await svc.submit_manager_review(
        guest_id=guest_id,
        reservation_id=review_data.reservation_id,
        property_id=review_data.property_id,
        overall_rating=review_data.overall_rating,
        body=review_data.body,
        category_ratings=review_data.category_ratings,
        reviewed_by=review_data.reviewed_by,
    )
    return {
        "id": str(review.id),
        "overall_rating": review.overall_rating,
        "direction": review.direction,
    }


@router.post("/reviews/{review_id}/respond", response_model=Dict)
async def respond_to_review(
    review_id: UUID,
    response: ReviewResponse,
    db: AsyncSession = Depends(get_db)
):
    """Add a response to a guest review"""
    svc = GuestManagementService(db)
    try:
        review = await svc.respond_to_review(
            review_id, response.response_body, response.responded_by
        )
        return {"status": "success", "review_id": str(review.id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/reviews/analytics", response_model=Dict)
async def review_analytics(
    property_id: Optional[UUID] = Query(None),
    days: int = Query(90),
    db: AsyncSession = Depends(get_db)
):
    """Review analytics and trends"""
    svc = GuestManagementService(db)
    return await svc.get_review_analytics(property_id=property_id, days=days)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SURVEYS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/{guest_id}/surveys/send", response_model=Dict, status_code=201)
async def send_survey(
    guest_id: UUID,
    reservation_id: UUID = Body(...),
    template_id: UUID = Body(...),
    send_method: str = Body("sms"),
    db: AsyncSession = Depends(get_db)
):
    """Send a survey to a guest"""
    svc = GuestManagementService(db)
    try:
        survey = await svc.send_survey(
            guest_id, reservation_id, template_id, send_method
        )
        return {
            "id": str(survey.id),
            "survey_url": survey.survey_url,
            "status": survey.status,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/surveys/{survey_id}/respond", response_model=Dict)
async def submit_survey_response(
    survey_id: UUID,
    data: SurveyResponseSubmit,
    db: AsyncSession = Depends(get_db)
):
    """Submit a completed survey response"""
    svc = GuestManagementService(db)
    try:
        survey = await svc.submit_survey_response(survey_id, data.responses)
        return {
            "id": str(survey.id),
            "overall_score": float(survey.overall_score) if survey.overall_score else None,
            "nps_score": survey.nps_score,
            "nps_category": survey.nps_category,
            "status": survey.status,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/surveys/nps", response_model=Dict)
async def get_nps(
    property_id: Optional[UUID] = Query(None),
    days: int = Query(90),
    db: AsyncSession = Depends(get_db)
):
    """Get Net Promoter Score"""
    svc = GuestManagementService(db)
    return await svc.get_nps_score(property_id=property_id, days=days)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLACKLIST / VIP / FLAGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/{guest_id}/blacklist", response_model=Dict)
async def blacklist_guest(
    guest_id: UUID,
    data: BlacklistRequest,
    db: AsyncSession = Depends(get_db)
):
    """Add guest to blacklist"""
    svc = GuestManagementService(db)
    try:
        guest = await svc.blacklist_guest(guest_id, data.reason, data.blacklisted_by)
        return {"status": "blacklisted", "guest_id": str(guest.id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{guest_id}/blacklist", response_model=Dict)
async def remove_blacklist(
    guest_id: UUID,
    removed_by: str = Query("admin"),
    db: AsyncSession = Depends(get_db)
):
    """Remove guest from blacklist"""
    svc = GuestManagementService(db)
    try:
        guest = await svc.remove_from_blacklist(guest_id, removed_by)
        return {"status": "removed", "guest_id": str(guest.id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{guest_id}/vip", response_model=Dict)
async def toggle_vip_status(
    guest_id: UUID,
    data: VIPToggle,
    db: AsyncSession = Depends(get_db)
):
    """Toggle VIP status"""
    svc = GuestManagementService(db)
    try:
        guest = await svc.toggle_vip(guest_id, data.is_vip, data.by)
        return {"status": "updated", "is_vip": guest.is_vip}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACTIVITY TIMELINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{guest_id}/activity", response_model=List[Dict])
async def get_activity_timeline(
    guest_id: UUID,
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Get guest activity timeline"""
    svc = GuestManagementService(db)
    activities = await svc._get_recent_activities(guest_id, limit=limit)
    if category:
        activities = [a for a in activities if a["category"] == category]
    return activities
