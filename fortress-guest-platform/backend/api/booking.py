"""
Booking & Availability API — Direct booking engine for guests
"""
from typing import Optional, List
from uuid import UUID
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.services.direct_booking import DirectBookingEngine
from backend.services.reservation_engine import ReservationEngine

router = APIRouter()
booking_engine = DirectBookingEngine()
reservation_engine = ReservationEngine()


class AvailabilityRequest(BaseModel):
    property_id: UUID
    check_in: date
    check_out: date
    guests: int = 2


class QuoteRequest(BaseModel):
    property_id: UUID
    check_in: date
    check_out: date
    guests: int = 2


class BookingRequest(BaseModel):
    quote_id: str
    first_name: str
    last_name: str
    email: str
    phone: str


class CancelRequest(BaseModel):
    reason: Optional[str] = "Guest requested"


class ReservationCreate(BaseModel):
    property_id: UUID
    guest_id: UUID
    check_in_date: date
    check_out_date: date
    num_guests: int = 2
    num_adults: Optional[int] = None
    num_children: Optional[int] = None
    booking_source: str = "direct"
    total_amount: Optional[float] = None
    internal_notes: Optional[str] = None


class CheckInOut(BaseModel):
    reservation_id: UUID


@router.post("/check-availability")
async def check_availability(req: AvailabilityRequest, db: AsyncSession = Depends(get_db)):
    """Check if dates are available for a property."""
    result = await booking_engine.check_availability(
        property_id=req.property_id,
        check_in=req.check_in,
        check_out=req.check_out,
        guests=req.guests,
        db=db,
    )
    return {
        "available": result.available,
        "reason": result.reason,
        "alternative_dates": result.alternative_dates,
    }


@router.post("/quote")
async def create_quote(req: QuoteRequest, db: AsyncSession = Depends(get_db)):
    """Generate a booking quote with full pricing breakdown."""
    quote = await booking_engine.create_quote(
        property_id=req.property_id,
        check_in=req.check_in,
        check_out=req.check_out,
        guests=req.guests,
        db=db,
    )
    return quote.__dict__ if hasattr(quote, '__dict__') else quote


@router.post("/reserve")
async def initiate_booking(req: BookingRequest, db: AsyncSession = Depends(get_db)):
    """Initiate a booking from a quote."""
    guest_info = {
        "first_name": req.first_name,
        "last_name": req.last_name,
        "email": req.email,
        "phone": req.phone,
    }
    result = await booking_engine.initiate_booking(
        quote_id=req.quote_id,
        guest_info=guest_info,
        db=db,
    )
    return result.__dict__ if hasattr(result, '__dict__') else result


@router.post("/cancel/{booking_id}")
async def cancel_booking(
    booking_id: str,
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a booking."""
    result = await booking_engine.cancel_booking(
        booking_id=booking_id,
        reason=req.reason,
        db=db,
    )
    return result.__dict__ if hasattr(result, '__dict__') else result


@router.get("/calendar/{property_id}")
async def property_calendar(
    property_id: UUID,
    month: int = Query(default=None),
    year: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get monthly availability calendar for a property."""
    if not month:
        month = datetime.utcnow().month
    if not year:
        year = datetime.utcnow().year
    return await reservation_engine.get_calendar(db, property_id, month, year)


@router.get("/search")
async def search_available(
    check_in: date = Query(...),
    check_out: date = Query(...),
    guests: int = Query(default=2),
    db: AsyncSession = Depends(get_db),
):
    """Search all available properties for dates."""
    return await booking_engine.search_available_properties(
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        amenities=None,
        db=db,
    )


@router.post("/reservations/create")
async def create_reservation(req: ReservationCreate, db: AsyncSession = Depends(get_db)):
    """Create a reservation directly (admin/staff use)."""
    data = req.model_dump()
    return await reservation_engine.create_reservation(db, data)


@router.post("/reservations/{reservation_id}/check-in")
async def check_in(reservation_id: UUID, db: AsyncSession = Depends(get_db)):
    """Check in a guest."""
    return await reservation_engine.check_in(db, reservation_id)


@router.post("/reservations/{reservation_id}/check-out")
async def check_out(reservation_id: UUID, db: AsyncSession = Depends(get_db)):
    """Check out a guest."""
    return await reservation_engine.check_out(db, reservation_id)


@router.get("/reservations/arrivals")
async def upcoming_arrivals(
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Get upcoming arrivals."""
    return await reservation_engine.get_upcoming_arrivals(db, days)


@router.get("/reservations/departures")
async def upcoming_departures(
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Get upcoming departures."""
    return await reservation_engine.get_upcoming_departures(db, days)


@router.get("/reservations/occupancy")
async def occupancy_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get occupancy report for date range."""
    return await reservation_engine.get_occupancy_report(db, start_date, end_date)


@router.get("/reservations/search")
async def search_reservations(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
):
    """Search reservations by confirmation code, guest name, etc."""
    return await reservation_engine.search_reservations(db, q)


@router.get("/pricing/{property_id}")
async def get_pricing(
    property_id: UUID,
    check_in: date = Query(...),
    check_out: date = Query(...),
    guests: int = Query(default=2),
    db: AsyncSession = Depends(get_db),
):
    """Get dynamic pricing for a property and dates."""
    from backend.services.pricing_engine import PricingEngine
    engine = PricingEngine()
    return await engine.calculate_stay_price(property_id, check_in, check_out, guests, db)
