"""
Housekeeping API — Turnover scheduling and cleaning management
"""
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models import Reservation, Property, Guest
from backend.services.housekeeping_service import HousekeepingService, HousekeepingTask

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


class AssignCleanerRequest(BaseModel):
    cleaner_name: str


class CompleteTurnoverRequest(BaseModel):
    notes: Optional[str] = ""
    photos_count: int = 0


def _svc(db: AsyncSession) -> HousekeepingService:
    return HousekeepingService(db)


@router.get("/today")
async def todays_schedule(db: AsyncSession = Depends(get_db)):
    """Get all housekeeping tasks for today."""
    return await _svc(db).get_todays_schedule()


@router.get("/week")
async def weekly_schedule(
    start_date: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get housekeeping schedule for the week."""
    start = start_date or date.today()
    return await _svc(db).get_weekly_schedule(start)


@router.post("/schedule/{reservation_id}")
async def schedule_turnover(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Schedule a turnover cleaning for a reservation checkout."""
    task = await _svc(db).schedule_turnover(reservation_id)
    return {"status": "scheduled", "task_id": str(task.id), "date": str(task.scheduled_date)}


@router.post("/{task_id}/assign")
async def assign_cleaner(
    task_id: UUID,
    req: AssignCleanerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Assign a cleaner to a housekeeping task."""
    task = await _svc(db).assign_cleaner(task_id, req.cleaner_name)
    return {"status": "assigned", "assigned_to": task.assigned_to}


@router.post("/{task_id}/complete")
async def complete_turnover(
    task_id: UUID,
    req: CompleteTurnoverRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark a housekeeping task as complete."""
    task = await _svc(db).complete_turnover(task_id, req.notes, req.photos_count)
    return {"status": "completed", "actual_minutes": task.actual_minutes}


@router.get("/status/{property_id}")
async def cleaning_status(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get current cleaning status for a property."""
    return await _svc(db).get_cleaning_status(property_id)


@router.get("/linen/{property_id}")
async def linen_requirements(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get linen requirements for a property."""
    return await _svc(db).get_linen_requirements(property_id)


@router.post("/mark-clean/{property_id}")
async def mark_property_clean(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark a property as clean. Completes any pending task or creates a completed one."""
    today = date.today()
    result = await db.execute(
        select(HousekeepingTask)
        .where(
            and_(
                HousekeepingTask.property_id == property_id,
                HousekeepingTask.scheduled_date == today,
                HousekeepingTask.status.in_(["pending", "in_progress"]),
            )
        )
        .limit(1)
    )
    task = result.scalars().first()

    from datetime import datetime
    if task:
        task.status = "completed"
        task.completed_at = datetime.utcnow()
    else:
        task = HousekeepingTask(
            property_id=property_id,
            scheduled_date=today,
            status="completed",
            cleaning_type="turnover",
            completed_at=datetime.utcnow(),
            notes="Manually marked clean via Housekeeping Panel",
        )
        db.add(task)

    await db.commit()
    return {"status": "completed", "property_id": str(property_id), "task_id": str(task.id)}


@router.get("/dirty-turnovers")
async def dirty_turnovers(
    target_date: Optional[date] = Query(default=None, description="Date to check (default: today)"),
    db: AsyncSession = Depends(get_db),
):
    """Get properties that need turnover cleaning due to checkouts.

    Returns properties checking out on the target date with their
    current housekeeping status (dirty, cleaning_in_progress, or clean).
    """
    import pytz
    et_today = datetime.now(pytz.timezone("America/New_York")).date()
    check_date = target_date or et_today

    checkout_result = await db.execute(
        select(Reservation, Property, Guest)
        .join(Property, Reservation.property_id == Property.id)
        .join(Guest, Reservation.guest_id == Guest.id)
        .where(
            and_(
                Reservation.check_out_date == check_date,
                Reservation.status.in_(["confirmed", "checked_in", "checked_out", "no_show"]),
            )
        )
        .order_by(Property.name)
    )
    checkouts = checkout_result.all()

    turnovers = []
    for res, prop, guest in checkouts:
        hk_result = await db.execute(
            select(HousekeepingTask)
            .where(
                and_(
                    HousekeepingTask.property_id == prop.id,
                    HousekeepingTask.scheduled_date == check_date,
                    HousekeepingTask.status != "cancelled",
                )
            )
            .order_by(HousekeepingTask.created_at.desc())
            .limit(1)
        )
        task = hk_result.scalars().first()

        if task:
            if task.status == "completed":
                clean_status = "clean"
            elif task.status == "in_progress":
                clean_status = "cleaning_in_progress"
            else:
                clean_status = "dirty"
            assigned_to = task.assigned_to
            task_id = str(task.id)
            estimated_minutes = task.estimated_minutes
            dispatched_by = task.dispatched_by
        else:
            clean_status = "dirty"
            assigned_to = None
            task_id = None
            estimated_minutes = None
            dispatched_by = None

        turnovers.append({
            "property_id": str(prop.id),
            "property_name": prop.name,
            "reservation_id": str(res.id),
            "confirmation_code": res.confirmation_code,
            "guest_name": f"{guest.first_name} {guest.last_name}",
            "check_in_date": str(res.check_in_date),
            "check_out_date": str(res.check_out_date),
            "reservation_status": res.status,
            "clean_status": clean_status,
            "assigned_to": assigned_to,
            "task_id": task_id,
            "estimated_minutes": estimated_minutes,
            "dispatched_by": dispatched_by,
            "needs_attention": clean_status != "clean",
        })

    dirty_count = sum(1 for t in turnovers if t["needs_attention"])

    return {
        "date": str(check_date),
        "total_checkouts": len(turnovers),
        "dirty_count": dirty_count,
        "clean_count": len(turnovers) - dirty_count,
        "turnovers": turnovers,
    }


@router.post("/dispatch/{reservation_id}")
async def ai_dispatch_turnover(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """AI-powered turnover dispatch: evaluate + assign + create task."""
    from backend.services.housekeeping_agent import dispatch_turnover
    res = await db.get(Reservation, reservation_id)
    if not res:
        from fastapi import HTTPException
        raise HTTPException(404, "Reservation not found")
    return await dispatch_turnover(reservation_id, res.property_id, db)


@router.get("/evaluate/{reservation_id}")
async def ai_evaluate_turnover(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """AI evaluation only (no task creation): estimate time + identify cleaner."""
    from backend.services.housekeeping_agent import evaluate_turnover
    res = await db.get(Reservation, reservation_id)
    if not res:
        from fastapi import HTTPException
        raise HTTPException(404, "Reservation not found")
    return await evaluate_turnover(reservation_id, res.property_id, db)


@router.post("/auto-schedule")
async def auto_schedule(db: AsyncSession = Depends(get_db)):
    """Auto-schedule turnovers from upcoming checkouts."""
    return await _svc(db).auto_schedule_from_reservations()
