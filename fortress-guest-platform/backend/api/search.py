"""
Global Search API - Cross-entity search across the platform
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from backend.core.database import get_db
from backend.models import Property, Guest, Reservation

router = APIRouter()


@router.get("/")
async def global_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Search across properties, guests, and reservations.
    Returns results grouped by entity type.
    """
    term = f"%{q.strip()}%"

    prop_result = await db.execute(
        select(Property)
        .where(Property.name.ilike(term))
        .limit(limit)
    )
    properties = [
        {
            "id": str(p.id),
            "name": p.name,
            "property_type": p.property_type,
            "is_active": p.is_active,
        }
        for p in prop_result.scalars().all()
    ]

    guest_result = await db.execute(
        select(Guest)
        .where(
            or_(
                Guest.first_name.ilike(term),
                Guest.last_name.ilike(term),
                Guest.email.ilike(term),
                Guest.phone_number.ilike(term),
            )
        )
        .limit(limit)
    )
    guests = [
        {
            "id": str(g.id),
            "first_name": g.first_name,
            "last_name": g.last_name,
            "email": g.email,
            "phone_number": g.phone_number,
        }
        for g in guest_result.scalars().all()
    ]

    res_result = await db.execute(
        select(Reservation)
        .where(Reservation.confirmation_code.ilike(term))
        .limit(limit)
    )
    reservations = [
        {
            "id": str(r.id),
            "confirmation_code": r.confirmation_code,
            "status": r.status,
            "check_in_date": str(r.check_in_date) if r.check_in_date else None,
            "check_out_date": str(r.check_out_date) if r.check_out_date else None,
        }
        for r in res_result.scalars().all()
    ]

    return {
        "query": q,
        "properties": properties,
        "guests": guests,
        "reservations": reservations,
        "total": len(properties) + len(guests) + len(reservations),
    }
