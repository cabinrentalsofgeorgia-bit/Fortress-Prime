"""
Guest Portal API — Self-service guest endpoints (no auth required).
Each guest accesses their portal via a unique reservation-linked URL.
"""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from backend.core.database import get_db

router = APIRouter()


@router.get("/{confirmation_code}")
async def get_portal(confirmation_code: str, db: AsyncSession = Depends(get_db)):
    """
    Fetch all portal data for a reservation.
    Returns property info, reservation details, guides, access codes, and extras.
    """
    res = await db.execute(
        text("""
            SELECT r.*, p.name as property_name, p.slug as property_slug,
                   p.bedrooms, p.bathrooms, p.max_guests,
                   p.wifi_ssid, p.wifi_password,
                   p.access_code_type, p.access_code_location,
                   p.parking_instructions, p.address,
                   g.first_name, g.last_name, g.phone_number, g.email
            FROM reservations r
            JOIN properties p ON r.property_id = p.id
            LEFT JOIN guests g ON r.guest_id = g.id
            WHERE r.confirmation_code = :code
        """),
        {"code": confirmation_code},
    )
    row = res.fetchone()
    if not row:
        raise HTTPException(404, "Reservation not found")

    data = dict(row._mapping)
    today = date.today()
    ci = data["check_in_date"]
    co = data["check_out_date"]

    if isinstance(ci, str):
        ci = date.fromisoformat(ci)
    if isinstance(co, str):
        co = date.fromisoformat(co)

    if today < ci:
        phase = "pre_arrival"
    elif today <= co:
        phase = "during_stay"
    else:
        phase = "post_checkout"

    guides = await db.execute(
        text("""
            SELECT title, content, category, display_order
            FROM guestbook_guides
            WHERE (property_id = :pid OR property_id IS NULL)
            AND is_active = true
            ORDER BY display_order, title
        """),
        {"pid": data["property_id"]},
    )

    extras = await db.execute(
        text("""
            SELECT id, name, description, price, category
            FROM extras_catalog
            WHERE is_active = true
            ORDER BY category, name
        """),
    )

    return {
        "reservation": {
            "confirmation_code": data["confirmation_code"],
            "check_in": str(ci),
            "check_out": str(co),
            "num_guests": data["num_guests"],
            "status": data["status"],
            "special_requests": data.get("special_requests"),
        },
        "guest": {
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
        },
        "property": {
            "name": data["property_name"],
            "slug": data["property_slug"],
            "bedrooms": data["bedrooms"],
            "bathrooms": data["bathrooms"],
            "max_guests": data["max_guests"],
            "address": data.get("address"),
            "wifi": {
                "ssid": data.get("wifi_ssid"),
                "password": data.get("wifi_password"),
            } if phase != "pre_arrival" else None,
            "access": {
                "type": data.get("access_code_type"),
                "location": data.get("access_code_location"),
                "code": data.get("access_code") if phase != "post_checkout" else None,
            } if phase != "pre_arrival" else None,
            "parking": data.get("parking_instructions"),
        },
        "phase": phase,
        "guides": [dict(r._mapping) for r in guides.fetchall()],
        "extras": [dict(r._mapping) for r in extras.fetchall()],
    }


class MaintenanceRequest(BaseModel):
    description: str
    urgency: str = "medium"


@router.post("/{confirmation_code}/maintenance")
async def submit_maintenance_request(
    confirmation_code: str,
    body: MaintenanceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Guest submits a maintenance/issue request during their stay."""
    res = await db.execute(
        text("""
            SELECT r.id, r.property_id, r.guest_id, p.name as property_name
            FROM reservations r
            JOIN properties p ON r.property_id = p.id
            WHERE r.confirmation_code = :code
            AND r.status IN ('confirmed', 'checked_in')
        """),
        {"code": confirmation_code},
    )
    row = res.fetchone()
    if not row:
        raise HTTPException(404, "Active reservation not found")

    data = dict(row._mapping)

    import uuid
    ticket = f"WO-{uuid.uuid4().hex[:6].upper()}"

    await db.execute(
        text("""
            INSERT INTO work_orders (
                ticket_number, property_id, reservation_id, guest_id,
                title, description, category, priority, status
            ) VALUES (
                :ticket, :property_id, :reservation_id, :guest_id,
                :title, :description, 'maintenance', :priority, 'open'
            )
        """),
        {
            "ticket": ticket,
            "property_id": data["property_id"],
            "reservation_id": data["id"],
            "guest_id": data["guest_id"],
            "title": f"Guest request: {body.description[:60]}",
            "description": body.description,
            "priority": "high" if body.urgency == "urgent" else body.urgency,
        },
    )
    await db.commit()

    return {"ticket_number": ticket, "status": "submitted", "property": data["property_name"]}


class ExtraOrderRequest(BaseModel):
    extra_id: str
    quantity: int = 1
    notes: Optional[str] = None


@router.post("/{confirmation_code}/extras")
async def order_extra(
    confirmation_code: str,
    body: ExtraOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Guest orders an add-on/upsell from the marketplace."""
    res = await db.execute(
        text("""
            SELECT r.id, r.guest_id FROM reservations r
            WHERE r.confirmation_code = :code
            AND r.status IN ('confirmed', 'checked_in')
        """),
        {"code": confirmation_code},
    )
    row = res.fetchone()
    if not row:
        raise HTTPException(404, "Active reservation not found")

    extra = await db.execute(
        text("SELECT * FROM extras_catalog WHERE id = :id AND is_active = true"),
        {"id": body.extra_id},
    )
    extra_row = extra.fetchone()
    if not extra_row:
        raise HTTPException(404, "Extra not found")

    extra_data = dict(extra_row._mapping)
    total = float(extra_data["price"]) * body.quantity

    return {
        "status": "ordered",
        "extra": extra_data["name"],
        "quantity": body.quantity,
        "total": total,
        "notes": body.notes,
    }
