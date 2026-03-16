"""
Housekeeping AI Agent — Autonomous Turnover Dispatch Brain
============================================================
Evaluates checkout reservations, calculates estimated cleaning time
based on property size, guest count, pet presence, and stay duration,
identifies the default housekeeper, and produces a structured dispatch
payload ready for SMS/webhook notification.

Designed for autonomous operation: the Board of Directors or the
daily automation loop can invoke evaluate_turnover() to dispatch
cleaners without human intervention.
"""

from datetime import date
from typing import Dict
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.models.guest import Guest
from backend.models.staff import StaffUser
from backend.services.housekeeping_service import HousekeepingTask

logger = structlog.get_logger()

# Cleaning time estimates (minutes) by bedroom count
BASE_CLEAN_MINUTES = {
    1: 90,
    2: 120,
    3: 150,
    4: 180,
    5: 210,
    6: 240,
}

PET_SURCHARGE_MINUTES = 30
LONG_STAY_THRESHOLD_DAYS = 7
LONG_STAY_SURCHARGE_MINUTES = 20
HIGH_OCCUPANCY_THRESHOLD = 0.8
HIGH_OCCUPANCY_SURCHARGE_MINUTES = 15
DEEP_CLEAN_MULTIPLIER = 1.5


async def evaluate_turnover(
    reservation_id: UUID,
    property_id: UUID,
    db: AsyncSession,
) -> Dict:
    """Evaluate a checkout and produce a structured dispatch payload.

    Calculates estimated cleaning time, identifies the default
    housekeeper, and returns everything needed to dispatch a cleaner.

    Returns:
        Dict with keys: property_name, guest_name, estimated_minutes,
        cleaning_type, assigned_to, assigned_phone, factors, dispatch_ready
    """
    reservation = await db.get(Reservation, reservation_id)
    prop = await db.get(Property, property_id)
    guest = await db.get(Guest, reservation.guest_id) if reservation else None

    if not reservation or not prop:
        return {"error": "Reservation or property not found", "dispatch_ready": False}

    # Calculate stay duration
    stay_days = 0
    if reservation.check_in_date and reservation.check_out_date:
        stay_days = (reservation.check_out_date - reservation.check_in_date).days

    # Determine base cleaning time from bedroom count
    bedrooms = int(prop.bedrooms or 2)
    base_minutes = BASE_CLEAN_MINUTES.get(bedrooms, BASE_CLEAN_MINUTES.get(3, 150))

    # Use property's custom default if set
    if prop.default_clean_minutes:
        base_minutes = prop.default_clean_minutes

    factors = []
    total_minutes = base_minutes
    factors.append(f"Base: {base_minutes}min ({bedrooms}BR)")

    # Pet surcharge
    num_pets = reservation.num_pets or 0
    if num_pets > 0:
        total_minutes += PET_SURCHARGE_MINUTES
        factors.append(f"+{PET_SURCHARGE_MINUTES}min (pets: {num_pets})")

    # Long stay surcharge
    if stay_days >= LONG_STAY_THRESHOLD_DAYS:
        total_minutes += LONG_STAY_SURCHARGE_MINUTES
        factors.append(f"+{LONG_STAY_SURCHARGE_MINUTES}min (long stay: {stay_days} nights)")

    # High occupancy surcharge
    max_guests = prop.max_guests or 8
    num_guests = reservation.num_guests or 1
    if max_guests > 0 and (num_guests / max_guests) >= HIGH_OCCUPANCY_THRESHOLD:
        total_minutes += HIGH_OCCUPANCY_SURCHARGE_MINUTES
        factors.append(f"+{HIGH_OCCUPANCY_SURCHARGE_MINUTES}min (high occupancy: {num_guests}/{max_guests})")

    # Determine cleaning type
    cleaning_type = "turnover"
    if stay_days >= 14 or num_pets >= 3:
        cleaning_type = "deep_clean"
        total_minutes = int(total_minutes * DEEP_CLEAN_MULTIPLIER)
        factors.append(f"Upgraded to deep clean (x{DEEP_CLEAN_MULTIPLIER})")

    # Identify default housekeeper
    assigned_to = None
    assigned_phone = None
    assigned_id = None

    if prop.default_housekeeper_id:
        housekeeper = await db.get(StaffUser, prop.default_housekeeper_id)
        if housekeeper and housekeeper.is_active:
            assigned_to = f"{housekeeper.first_name} {housekeeper.last_name}"
            assigned_phone = housekeeper.notification_phone
            assigned_id = str(housekeeper.id)

    guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Unknown"

    payload = {
        "property_id": str(prop.id),
        "property_name": prop.name,
        "reservation_id": str(reservation.id),
        "confirmation_code": reservation.confirmation_code,
        "guest_name": guest_name,
        "check_out_date": str(reservation.check_out_date),
        "num_guests": num_guests,
        "num_pets": num_pets,
        "stay_nights": stay_days,
        "bedrooms": bedrooms,
        "estimated_minutes": total_minutes,
        "cleaning_type": cleaning_type,
        "assigned_to": assigned_to,
        "assigned_phone": assigned_phone,
        "assigned_id": assigned_id,
        "factors": factors,
        "dispatch_ready": bool(assigned_to),
        "dispatch_message": _build_dispatch_sms(
            prop.name, guest_name, reservation.check_out_date,
            total_minutes, cleaning_type, num_pets,
        ) if assigned_to else None,
    }

    logger.info(
        "turnover_evaluated",
        property=prop.name,
        estimated_minutes=total_minutes,
        cleaning_type=cleaning_type,
        assigned_to=assigned_to,
        factors=len(factors),
    )

    return payload


async def dispatch_turnover(
    reservation_id: UUID,
    property_id: UUID,
    db: AsyncSession,
) -> Dict:
    """Evaluate + create the housekeeping task + return dispatch payload.

    This is the full agentic dispatch: evaluates the turnover, creates
    (or updates) the HousekeepingTask in the DB, and returns the payload
    ready for SMS notification.
    """
    evaluation = await evaluate_turnover(reservation_id, property_id, db)

    if evaluation.get("error"):
        return evaluation

    reservation = await db.get(Reservation, reservation_id)
    check_date = reservation.check_out_date if reservation else date.today()

    from sqlalchemy import and_
    existing = await db.execute(
        select(HousekeepingTask).where(
            and_(
                HousekeepingTask.property_id == property_id,
                HousekeepingTask.scheduled_date == check_date,
                HousekeepingTask.status.in_(["pending", "in_progress"]),
            )
        ).limit(1)
    )
    task = existing.scalars().first()

    if task:
        task.assigned_to = evaluation["assigned_to"] or task.assigned_to
        task.estimated_minutes = evaluation["estimated_minutes"]
        task.cleaning_type = evaluation["cleaning_type"]
        task.dispatched_by = "ai_agent"
        task.dispatch_payload = evaluation
    else:
        task = HousekeepingTask(
            property_id=property_id,
            reservation_id=reservation_id,
            scheduled_date=check_date,
            status="pending",
            assigned_to=evaluation["assigned_to"],
            cleaning_type=evaluation["cleaning_type"],
            estimated_minutes=evaluation["estimated_minutes"],
            dispatched_by="ai_agent",
            dispatch_payload=evaluation,
        )
        db.add(task)

    await db.commit()

    evaluation["task_id"] = str(task.id)
    evaluation["task_status"] = task.status

    # Send SMS to the assigned cleaner
    sms_sent = False
    if evaluation.get("assigned_phone") and evaluation.get("dispatch_message"):
        try:
            from backend.integrations.twilio_client import TwilioClient
            twilio = TwilioClient()
            await twilio.send_sms(
                to=evaluation["assigned_phone"],
                body=evaluation["dispatch_message"],
            )
            sms_sent = True
            logger.info(
                "turnover_sms_dispatched",
                property=evaluation["property_name"],
                phone=evaluation["assigned_phone"][:6] + "...",
            )
        except Exception as e:
            logger.critical(
                "turnover_sms_failed",
                property=evaluation["property_name"],
                phone=evaluation.get("assigned_phone"),
                error=str(e)[:200],
            )

    evaluation["sms_sent"] = sms_sent

    logger.info(
        "turnover_dispatched",
        property=evaluation["property_name"],
        task_id=str(task.id),
        assigned_to=evaluation["assigned_to"],
        estimated_minutes=evaluation["estimated_minutes"],
        sms_sent=sms_sent,
    )

    return evaluation


def _build_dispatch_sms(
    property_name: str,
    guest_name: str,
    check_out_date,
    estimated_minutes: int,
    cleaning_type: str,
    num_pets: int,
) -> str:
    """Build the SMS message for cleaner dispatch."""
    hours = estimated_minutes // 60
    mins = estimated_minutes % 60
    time_str = f"{hours}h {mins}m" if hours else f"{mins}min"

    msg = (
        f"CROG Turnover Assignment\n\n"
        f"Property: {property_name}\n"
        f"Checkout: {check_out_date}\n"
        f"Type: {cleaning_type.replace('_', ' ').title()}\n"
        f"Est. Time: {time_str}\n"
    )
    if num_pets > 0:
        msg += f"Pets: {num_pets} (extra cleaning needed)\n"
    msg += f"\nGuest: {guest_name}\n"
    msg += "\nReply DONE when complete."
    return msg
