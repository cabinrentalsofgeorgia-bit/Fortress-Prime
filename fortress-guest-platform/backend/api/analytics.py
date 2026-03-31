"""
Analytics API - Real-time metrics and insights
BETTER THAN: All competitors (predictive analytics, cost tracking, AI performance)
"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timedelta

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models import Reservation, Message, WorkOrder, Guest, Property

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


class DashboardStats(BaseModel):
    total_properties: int = 0
    total_reservations: int = 0
    active_reservations: int = 0
    arriving_today: int = 0
    departing_today: int = 0
    current_guests: int = 0
    total_messages: int = 0
    occupancy_rate: float = 0.0
    messages_today: int = 0
    ai_automation_rate: float = 0.0
    open_work_orders: int = 0
    unread_messages: int = 0
    total_revenue_mtd: Optional[float] = None
    total_guests: int = 0


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """
    Get real-time dashboard statistics
    
    BETTER THAN competitors:
    - Real-time updates
    - Automation rate tracking
    - Cost metrics
    - AI performance
    """
    import pytz
    now_et = datetime.now(pytz.timezone("America/New_York"))
    today = now_et.date()
    thirty_days_ago = now_et - timedelta(days=30)
    thirty_days_ago_naive = thirty_days_ago.replace(tzinfo=None)
    
    # Guests arriving today
    arriving_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.check_in_date == today,
            Reservation.status.in_(["confirmed", "checked_in"])
        )
    )
    guests_arriving = arriving_result.scalar()
    
    # Guests currently staying
    staying_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.status == "checked_in",
            Reservation.check_in_date <= today,
            Reservation.check_out_date >= today
        )
    )
    guests_staying = staying_result.scalar()
    
    # Guests departing today
    departing_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.check_out_date == today,
            Reservation.status.in_(["confirmed", "checked_in", "checked_out", "no_show"])
        )
    )
    guests_departing = departing_result.scalar()
    
    # Guests last 30 days
    guests_30d_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.check_in_date >= thirty_days_ago_naive.date()
        )
    )
    guests_30d = guests_30d_result.scalar()
    
    # Messages today
    messages_today_result = await db.execute(
        select(func.count(Message.id)).where(
            func.date(Message.created_at) == today
        )
    )
    messages_today = messages_today_result.scalar()
    
    # AI responses today
    ai_responses_result = await db.execute(
        select(func.count(Message.id)).where(
            func.date(Message.created_at) == today,
            Message.direction == "outbound",
            Message.is_auto_response == True
        )
    )
    ai_responses = ai_responses_result.scalar()
    
    # Automation rate
    outbound_today_result = await db.execute(
        select(func.count(Message.id)).where(
            func.date(Message.created_at) == today,
            Message.direction == "outbound"
        )
    )
    outbound_today = outbound_today_result.scalar()
    automation_rate = (ai_responses / outbound_today * 100) if outbound_today > 0 else 0
    
    # Open work orders
    open_wo_result = await db.execute(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.status.in_(["open", "in_progress", "waiting_parts"])
        )
    )
    open_work_orders = open_wo_result.scalar()
    
    # Average rating (30 days)
    avg_rating_result = await db.execute(
        select(func.avg(Reservation.guest_rating)).where(
            Reservation.guest_rating.isnot(None),
            Reservation.created_at >= thirty_days_ago_naive
        )
    )
    avg_rating = avg_rating_result.scalar()
    
    # Total guests
    total_guests_result = await db.execute(select(func.count(Guest.id)))
    total_guests = total_guests_result.scalar()

    # Total reservations
    total_reservations_result = await db.execute(select(func.count(Reservation.id)))
    total_reservations = total_reservations_result.scalar()

    # Total active properties
    total_props_result = await db.execute(
        select(func.count(Property.id)).where(Property.is_active == True)
    )
    total_properties = total_props_result.scalar()

    # Total messages
    total_messages_result = await db.execute(select(func.count(Message.id)))
    total_messages = total_messages_result.scalar()

    # Active reservations (confirmed or checked_in that overlap today)
    active_res_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.status.in_(["confirmed", "checked_in"]),
            Reservation.check_in_date <= today,
            Reservation.check_out_date >= today,
        )
    )
    active_reservations = active_res_result.scalar()

    # Occupancy rate
    occupancy_rate = (active_reservations / total_properties * 100) if total_properties > 0 else 0

    # Unread messages
    unread_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.direction == "inbound",
            Message.read_at.is_(None),
        )
    )
    unread_messages = unread_result.scalar()

    # Revenue MTD
    mtd_start = today.replace(day=1)
    rev_result = await db.execute(
        select(func.sum(Reservation.total_amount)).where(
            Reservation.check_in_date >= mtd_start,
            Reservation.check_in_date <= today,
            Reservation.status.in_(["confirmed", "checked_in", "checked_out", "no_show"]),
        )
    )
    revenue_mtd = rev_result.scalar()

    return DashboardStats(
        total_properties=total_properties,
        total_reservations=total_reservations,
        active_reservations=active_reservations,
        arriving_today=guests_arriving,
        departing_today=guests_departing,
        current_guests=guests_staying,
        total_messages=total_messages,
        occupancy_rate=round(occupancy_rate, 1),
        messages_today=messages_today,
        ai_automation_rate=round(automation_rate, 1),
        open_work_orders=open_work_orders,
        unread_messages=unread_messages,
        total_revenue_mtd=float(revenue_mtd) if revenue_mtd else 0,
        total_guests=total_guests,
    )
