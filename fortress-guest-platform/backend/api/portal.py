"""
Guest Portal API - Personalized, contextual guest experience
=============================================================

Each guest gets a unique portal URL tied to their reservation.
The portal knows their property, their dates, and their context.

URL pattern: /portal/{confirmation_code}
This is the public-facing endpoint - no auth required (the confirmation
code itself is the access token, like an Airbnb message thread link).
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models import Reservation
from backend.services.guest_portal import GuestPortalService

router = APIRouter()


class ConciergeQuestion(BaseModel):
    question: str


class GuestMessage(BaseModel):
    message: str


class FeedbackSubmit(BaseModel):
    answer_id: Optional[str] = None
    helpful: bool
    comment: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PORTAL ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _resolve_reservation(
    confirmation_code: str, db: AsyncSession
) -> Reservation:
    """Look up reservation by confirmation code"""
    result = await db.execute(
        select(Reservation).where(
            Reservation.confirmation_code == confirmation_code
        )
    )
    res = result.scalar_one_or_none()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found. Please check your link.")
    return res


@router.get("/{confirmation_code}")
async def get_portal(
    confirmation_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the full personalized portal for a guest's reservation.
    
    This returns everything: essentials, guides, local recs,
    extras, contact info, and context-aware quick actions.
    
    The data changes based on:
    - Where they are in the stay lifecycle
    - The current season
    - Their specific property
    """
    reservation = await _resolve_reservation(confirmation_code, db)
    service = GuestPortalService(db)
    portal = await service.get_portal_data(reservation.id)
    if not portal:
        raise HTTPException(status_code=500, detail="Could not load portal data")
    return portal


@router.post("/{confirmation_code}/ask")
async def ask_concierge(
    confirmation_code: str,
    body: ConciergeQuestion,
    db: AsyncSession = Depends(get_db),
):
    """
    Ask the smart concierge a question.
    
    Returns a contextual, property-specific answer - not canned responses.
    If it can answer directly from data (WiFi, door code, check-in time),
    it does so with 100% confidence. For property-specific questions 
    (how does the fireplace work?), it pulls from the knowledge base.
    For anything it can't answer, it connects the guest to a human.
    """
    reservation = await _resolve_reservation(confirmation_code, db)
    service = GuestPortalService(db)
    result = await service.ask_concierge(reservation.id, body.question)
    return result


@router.post("/{confirmation_code}/message")
async def send_message(
    confirmation_code: str,
    body: GuestMessage,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a message from the guest portal.
    
    Attempts to answer immediately and creates a record for follow-up.
    The guest always gets an immediate response (even if it's "great 
    question, let me connect you with our team").
    """
    reservation = await _resolve_reservation(confirmation_code, db)
    service = GuestPortalService(db)
    result = await service.send_guest_message(reservation.id, body.message)
    return result


@router.post("/{confirmation_code}/feedback")
async def submit_feedback(
    confirmation_code: str,
    body: FeedbackSubmit,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback on a concierge answer.
    This improves future responses.
    """
    # Just accept for now - in the future this feeds back into the AI
    return {
        "status": "received",
        "message": "Thank you for your feedback! It helps us improve.",
    }
