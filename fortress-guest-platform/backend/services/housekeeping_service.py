"""
Housekeeping & Turnover Scheduler — Fortress Guest Platform
Replaces Streamline VRS housekeeping module with enterprise-grade automation.

Manages turnover scheduling, cleaner assignment, linen tracking, and inspection
workflows for 14 vacation rental cabins in Blue Ridge, Georgia.
"""
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import (
    Boolean, Column, String, Integer, Text, Date, Time, TIMESTAMP, ForeignKey,
    select, and_,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.models import Property, Reservation

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# SQLAlchemy Model
# ---------------------------------------------------------------------------

class HousekeepingTask(Base):
    """Housekeeping / turnover task for a property."""

    __tablename__ = "housekeeping_tasks"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reservation_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scheduled_date = Column(Date, nullable=False, index=True)
    scheduled_time = Column(Time, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending | in_progress | completed | cancelled
    assigned_to = Column(String(255), nullable=True)
    # Structured cleaner FK (migration 8bc70dafda91)
    legacy_assigned_to = Column(String(255), nullable=True)
    assigned_cleaner_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("cleaners.id", ondelete="SET NULL"),
        nullable=True,
    )
    cleaning_type = Column(
        String(20),
        nullable=False,
        default="turnover",
    )  # turnover | deep_clean | inspection | mid_stay
    estimated_minutes = Column(Integer, nullable=True)
    actual_minutes = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    streamline_source = Column(JSONB, nullable=True)
    streamline_synced_at = Column(TIMESTAMP, nullable=True)
    streamline_checklist_id = Column(String(100), nullable=True)
    # Agentic dispatch metadata
    dispatched_by = Column(String(50), nullable=True)  # manual | ai_agent | streamline
    dispatch_payload = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    # Relationships
    prop = relationship("Property", backref="housekeeping_tasks")
    reservation = relationship("Reservation", backref="housekeeping_tasks")

    def __repr__(self) -> str:
        return (
            f"<HousekeepingTask {self.cleaning_type} "
            f"property={self.property_id} date={self.scheduled_date}>"
        )


# ---------------------------------------------------------------------------
# Cleaning-time heuristics (minutes) by bedroom count
# ---------------------------------------------------------------------------
_BASE_CLEAN_MINUTES: Dict[int, int] = {
    1: 90,
    2: 120,
    3: 150,
    4: 180,
    5: 210,
    6: 240,
    7: 270,
}
_MINUTES_PER_BATHROOM = 20
_DEFAULT_CHECKOUT_TIME = time(11, 0)
_DEFAULT_CHECKIN_TIME = time(16, 0)

# Linen counts per bed configuration
_LINENS_PER_BEDROOM = {
    "sheet_sets": 1,
    "pillow_cases": 4,
    "duvet_covers": 1,
    "mattress_protectors": 1,
}
_LINENS_PER_BATHROOM = {
    "bath_towels": 2,
    "hand_towels": 2,
    "washcloths": 2,
    "bath_mats": 1,
}
_COMMON_LINENS = {
    "kitchen_towels": 4,
    "dish_cloths": 2,
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class HousekeepingService:
    """
    Enterprise turnover & housekeeping scheduler.

    Handles the full lifecycle: auto-scheduling from reservations, cleaner
    assignment, time estimation, linen requirements, and completion tracking.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="housekeeping")

    # ------------------------------------------------------------------
    # 1. Schedule a turnover from a specific reservation
    # ------------------------------------------------------------------
    async def schedule_turnover(self, reservation_id: UUID) -> HousekeepingTask:
        """Create a turnover task triggered by a reservation checkout."""

        reservation = await self.db.get(Reservation, reservation_id)
        if not reservation:
            raise ValueError(f"Reservation {reservation_id} not found")

        prop = await self.db.get(Property, reservation.property_id)
        est_minutes = self._estimate_minutes(prop)

        task = HousekeepingTask(
            property_id=reservation.property_id,
            reservation_id=reservation.id,
            scheduled_date=reservation.check_out_date,
            scheduled_time=_DEFAULT_CHECKOUT_TIME,
            status="pending",
            cleaning_type="turnover",
            estimated_minutes=est_minutes,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)

        self.log.info(
            "turnover_scheduled",
            task_id=str(task.id),
            property=prop.name if prop else str(reservation.property_id),
            date=str(reservation.check_out_date),
            estimated_minutes=est_minutes,
        )
        return task

    # ------------------------------------------------------------------
    # 2. Today's schedule
    # ------------------------------------------------------------------
    async def get_todays_schedule(self) -> List[Dict]:
        """Return every housekeeping task scheduled for today."""

        today = date.today()
        result = await self.db.execute(
            select(HousekeepingTask, Property.name)
            .join(Property, HousekeepingTask.property_id == Property.id)
            .where(HousekeepingTask.scheduled_date == today)
            .order_by(HousekeepingTask.scheduled_time.asc().nullslast())
        )
        rows = result.all()
        return [self._task_to_dict(task, prop_name) for task, prop_name in rows]

    # ------------------------------------------------------------------
    # 3. Weekly schedule
    # ------------------------------------------------------------------
    async def get_weekly_schedule(self, start_date: date) -> Dict[str, List[Dict]]:
        """Return a day-keyed dict of tasks for 7 days starting at *start_date*."""

        end_date = start_date + timedelta(days=6)
        result = await self.db.execute(
            select(HousekeepingTask, Property.name)
            .join(Property, HousekeepingTask.property_id == Property.id)
            .where(
                and_(
                    HousekeepingTask.scheduled_date >= start_date,
                    HousekeepingTask.scheduled_date <= end_date,
                )
            )
            .order_by(
                HousekeepingTask.scheduled_date.asc(),
                HousekeepingTask.scheduled_time.asc().nullslast(),
            )
        )
        rows = result.all()
        schedule: Dict[str, List[Dict]] = {}
        for task, prop_name in rows:
            key = task.scheduled_date.isoformat()
            schedule.setdefault(key, []).append(self._task_to_dict(task, prop_name))
        return schedule

    # ------------------------------------------------------------------
    # 4. Assign a cleaner
    # ------------------------------------------------------------------
    async def assign_cleaner(
        self,
        turnover_id: UUID,
        cleaner_name: str,
        cleaner_id: Optional[UUID] = None,
    ) -> HousekeepingTask:
        """Assign (or reassign) a cleaner to a housekeeping task.

        If *cleaner_id* is provided the FK is set; *cleaner_name* is always
        written to the legacy ``assigned_to`` column for backwards compatibility.
        """
        task = await self.db.get(HousekeepingTask, turnover_id)
        if not task:
            raise ValueError(f"Housekeeping task {turnover_id} not found")

        previous = task.assigned_to
        task.assigned_to = cleaner_name
        if cleaner_id is not None:
            task.assigned_cleaner_id = cleaner_id  # type: ignore[assignment]
        if task.status == "pending":
            task.status = "in_progress"
        await self.db.flush()

        self.log.info(
            "cleaner_assigned",
            task_id=str(turnover_id),
            cleaner=cleaner_name,
            cleaner_id=str(cleaner_id) if cleaner_id else None,
            previous=previous,
        )
        return task

    # ------------------------------------------------------------------
    # 5. Complete a turnover
    # ------------------------------------------------------------------
    async def complete_turnover(
        self,
        turnover_id: UUID,
        notes: Optional[str] = None,
        photos_count: int = 0,
    ) -> HousekeepingTask:
        """Mark a housekeeping task as completed with optional inspection notes."""

        task = await self.db.get(HousekeepingTask, turnover_id)
        if not task:
            raise ValueError(f"Housekeeping task {turnover_id} not found")
        if task.status == "completed":
            raise ValueError(f"Task {turnover_id} is already completed")

        now = datetime.utcnow()
        task.status = "completed"
        task.completed_at = now
        if notes:
            task.notes = notes

        # Calculate actual duration if we can infer a start time
        if task.scheduled_time and task.scheduled_date == date.today():
            start_dt = datetime.combine(task.scheduled_date, task.scheduled_time)
            task.actual_minutes = max(int((now - start_dt).total_seconds() / 60), 1)

        await self.db.flush()

        self.log.info(
            "turnover_completed",
            task_id=str(turnover_id),
            actual_minutes=task.actual_minutes,
            photos=photos_count,
        )
        return task

    # ------------------------------------------------------------------
    # 6. Cleaning status for a property
    # ------------------------------------------------------------------
    async def get_cleaning_status(self, property_id: UUID) -> Dict:
        """Return the most recent / upcoming cleaning status for a property."""

        today = date.today()
        result = await self.db.execute(
            select(HousekeepingTask)
            .where(
                and_(
                    HousekeepingTask.property_id == property_id,
                    HousekeepingTask.status != "cancelled",
                )
            )
            .order_by(HousekeepingTask.scheduled_date.desc())
            .limit(1)
        )
        task = result.scalars().first()
        if not task:
            return {
                "property_id": str(property_id),
                "status": "unknown",
                "message": "No housekeeping records found",
            }

        if task.status == "completed":
            ready = True
            label = "clean"
        elif task.scheduled_date <= today and task.status in ("pending", "in_progress"):
            ready = False
            label = "cleaning_in_progress" if task.status == "in_progress" else "dirty"
        else:
            ready = True
            label = "clean"

        return {
            "property_id": str(property_id),
            "status": label,
            "ready_for_guest": ready,
            "last_task_id": str(task.id),
            "last_task_date": task.scheduled_date.isoformat(),
            "assigned_to": task.assigned_to,
        }

    # ------------------------------------------------------------------
    # 7. Estimate cleaning time
    # ------------------------------------------------------------------
    async def estimate_cleaning_time(self, property_id: UUID) -> Dict:
        """Estimate turnaround time based on property dimensions."""

        prop = await self.db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        est = self._estimate_minutes(prop)
        return {
            "property_id": str(property_id),
            "property_name": prop.name,
            "bedrooms": prop.bedrooms,
            "bathrooms": float(prop.bathrooms),
            "estimated_minutes": est,
            "estimated_hours": round(est / 60, 1),
            "window": f"{_DEFAULT_CHECKOUT_TIME.strftime('%I:%M %p')} – "
                      f"{_DEFAULT_CHECKIN_TIME.strftime('%I:%M %p')}",
        }

    # ------------------------------------------------------------------
    # 8. Bulk auto-schedule from upcoming reservations
    # ------------------------------------------------------------------
    async def auto_schedule_from_reservations(
        self, db: Optional[AsyncSession] = None
    ) -> List[HousekeepingTask]:
        """Scan upcoming checkouts (next 14 days) and create turnover tasks
        for any that don't already have one."""

        session = db or self.db
        today = date.today()
        horizon = today + timedelta(days=14)

        # Reservations checking out soon
        res_result = await session.execute(
            select(Reservation).where(
                and_(
                    Reservation.check_out_date >= today,
                    Reservation.check_out_date <= horizon,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                )
            )
        )
        upcoming = res_result.scalars().all()

        # Already-scheduled task reservation IDs
        existing_result = await session.execute(
            select(HousekeepingTask.reservation_id).where(
                and_(
                    HousekeepingTask.reservation_id.isnot(None),
                    HousekeepingTask.status != "cancelled",
                )
            )
        )
        existing_ids = {row for row, in existing_result.all()}

        created: List[HousekeepingTask] = []
        for res in upcoming:
            if res.id in existing_ids:
                continue

            prop = await session.get(Property, res.property_id)
            est = self._estimate_minutes(prop)
            task = HousekeepingTask(
                property_id=res.property_id,
                reservation_id=res.id,
                scheduled_date=res.check_out_date,
                scheduled_time=_DEFAULT_CHECKOUT_TIME,
                status="pending",
                cleaning_type="turnover",
                estimated_minutes=est,
            )
            session.add(task)
            created.append(task)

        if created:
            await session.flush()

        self.log.info(
            "auto_schedule_complete",
            checked=len(upcoming),
            created=len(created),
        )
        return created

    # ------------------------------------------------------------------
    # 9. Linen requirements
    # ------------------------------------------------------------------
    async def get_linen_requirements(self, property_id: UUID) -> Dict:
        """Calculate linen needs based on bedroom/bathroom count."""

        prop = await self.db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        bedrooms = int(prop.bedrooms)
        bathrooms = int(prop.bathrooms)  # truncate halves for linen calc

        bedroom_linens = {
            k: v * bedrooms for k, v in _LINENS_PER_BEDROOM.items()
        }
        bathroom_linens = {
            k: v * bathrooms for k, v in _LINENS_PER_BATHROOM.items()
        }

        return {
            "property_id": str(property_id),
            "property_name": prop.name,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "bedroom_linens": bedroom_linens,
            "bathroom_linens": bathroom_linens,
            "common_linens": dict(_COMMON_LINENS),
            "total_items": (
                sum(bedroom_linens.values())
                + sum(bathroom_linens.values())
                + sum(_COMMON_LINENS.values())
            ),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _estimate_minutes(prop: Optional[Property]) -> int:
        """Heuristic cleaning-time estimate from bedroom + bathroom count."""
        if not prop:
            return 150  # sensible default

        bedrooms = int(prop.bedrooms)
        bathrooms = int(prop.bathrooms)
        base = _BASE_CLEAN_MINUTES.get(bedrooms, 270 + (bedrooms - 7) * 30)
        return base + bathrooms * _MINUTES_PER_BATHROOM

    @staticmethod
    def _task_to_dict(task: HousekeepingTask, prop_name: str) -> Dict:
        """Serialize a task row + property name into an API-friendly dict."""
        return {
            "id": str(task.id),
            "property_id": str(task.property_id),
            "property_name": prop_name,
            "reservation_id": str(task.reservation_id) if task.reservation_id else None,
            "scheduled_date": task.scheduled_date.isoformat(),
            "scheduled_time": task.scheduled_time.isoformat() if task.scheduled_time else None,
            "status": task.status,
            "assigned_to": task.assigned_to,
            "cleaning_type": task.cleaning_type,
            "estimated_minutes": task.estimated_minutes,
            "actual_minutes": task.actual_minutes,
            "notes": task.notes,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "assigned_cleaner_id": str(task.assigned_cleaner_id) if task.assigned_cleaner_id else None,
        }
