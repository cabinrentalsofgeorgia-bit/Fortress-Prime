"""
Reactivation Hunter drafting engine.

Builds contextual dormant-guest outreach drafts and persists them into the
Hunter approval queue for human review before delivery.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_queue import AgentQueue
from backend.models.guest import Guest
from backend.models.message import Message
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.services.crog_concierge_engine import (
    HYDRA_120B_URL,
    HYDRA_MODEL_120B,
    _call_llm,
)

logger = structlog.get_logger(service="hunter.reactivation")


def _initial_delivery_channel(guest: Guest) -> str:
    preferred = (guest.preferred_contact_method or "").strip().lower()
    return preferred if preferred in {"email", "sms"} else "email"


def _reservation_snapshot(reservation: Reservation, prop: Property | None) -> dict[str, Any]:
    return {
        "reservation_id": str(reservation.id),
        "property_id": str(reservation.property_id) if reservation.property_id else None,
        "property_name": prop.name if prop else None,
        "property_slug": prop.slug if prop else None,
        "check_in_date": reservation.check_in_date.isoformat() if reservation.check_in_date else None,
        "check_out_date": reservation.check_out_date.isoformat() if reservation.check_out_date else None,
        "status": reservation.status,
        "booking_source": reservation.booking_source,
        "total_amount": float(reservation.total_amount) if reservation.total_amount is not None else None,
        "num_guests": reservation.num_guests,
        "num_children": reservation.num_children,
        "num_pets": reservation.num_pets,
        "special_requests": (reservation.special_requests or "").strip() or None,
        "guest_feedback": (reservation.guest_feedback or "").strip() or None,
        "guest_rating": reservation.guest_rating,
    }


def _message_snapshot(message: Message) -> dict[str, Any]:
    return {
        "direction": message.direction,
        "body": (message.body or "").strip(),
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _favorite_property(reservations: list[dict[str, Any]]) -> dict[str, Any] | None:
    named = [reservation for reservation in reservations if reservation.get("property_name")]
    if not named:
        return None

    counts = Counter(str(reservation.get("property_name")) for reservation in named)
    ranked = sorted(
        named,
        key=lambda reservation: (
            counts[str(reservation.get("property_name"))],
            reservation.get("check_out_date") or "",
        ),
        reverse=True,
    )
    winner = ranked[0]
    return {
        "property_id": winner.get("property_id"),
        "property_name": winner.get("property_name"),
        "property_slug": winner.get("property_slug"),
        "visits": counts[str(winner.get("property_name"))],
    }


def _behavioral_signals(guest: Guest, reservations: list[dict[str, Any]]) -> list[str]:
    signals: list[str] = []
    if any((reservation.get("num_children") or 0) > 0 for reservation in reservations):
        signals.append("family travel")
    if any((reservation.get("num_pets") or 0) > 0 for reservation in reservations):
        signals.append("pet-friendly stays")
    if any("hot tub" in str(reservation.get("special_requests") or "").lower() for reservation in reservations):
        signals.append("amenity-driven booking intent")
    if guest.is_vip:
        signals.append("VIP guest")
    if (guest.loyalty_tier or "").strip():
        signals.append(f"loyalty tier: {guest.loyalty_tier}")
    return signals[:5]


def _fallback_draft(guest: Guest, favorite_property_name: str | None) -> str:
    first_name = (guest.first_name or guest.full_name or "there").strip()
    property_phrase = (
        f" at {favorite_property_name}" if favorite_property_name else ""
    )
    return (
        f"Hi {first_name}, we loved hosting you{property_phrase} with Cabin Rentals of Georgia. "
        "It has been a while since your last mountain stay, and we would love to help you plan another one. "
        "If you are thinking about a return trip, reply here and we can put together a few hand-picked options "
        "based on the cabins and trip style you have enjoyed before."
    )[:1600]


async def _generate_draft(
    *,
    guest: Guest,
    target_score: int,
    reservations: list[dict[str, Any]],
    recent_messages: list[dict[str, Any]],
    favorite_property: dict[str, Any] | None,
    signals: list[str],
) -> str:
    system = (
        "You write premium reactivation outreach for Cabin Rentals of Georgia. "
        "Draft one personalized message to win back a dormant high-value guest. "
        "Use only the facts in the context. Do not invent discounts, promo codes, or specific amenities. "
        "Warm Southern hospitality, concise, concrete, and high-touch. "
        "Output plain text only: the exact outreach message, no subject line, no JSON, no quotes."
    )
    user = f"""Generate a reactivation outreach draft for this dormant guest.

GUEST_PROFILE:
{json.dumps({
    "guest_id": str(guest.id),
    "full_name": guest.full_name,
    "email": guest.email,
    "lifetime_revenue": float(guest.lifetime_revenue or 0),
    "last_stay_date": guest.last_stay_date.isoformat() if guest.last_stay_date else None,
    "lifetime_stays": guest.lifetime_stays,
    "total_stays": guest.total_stays,
    "loyalty_tier": guest.loyalty_tier,
    "value_score": guest.value_score,
    "preferred_contact_method": guest.preferred_contact_method,
    "target_score": target_score,
}, ensure_ascii=False, indent=2)}

FAVORITE_PROPERTY:
{json.dumps(favorite_property or {}, ensure_ascii=False, indent=2)}

BEHAVIORAL_SIGNALS:
{json.dumps(signals, ensure_ascii=False)}

RECENT_STAY_HISTORY:
{json.dumps(reservations[:5], ensure_ascii=False, indent=2, default=str)}

RECENT_MESSAGE_HISTORY:
{json.dumps(recent_messages[:6], ensure_ascii=False, indent=2, default=str)}

Requirements:
- 90 to 180 words.
- Mention Cabin Rentals of Georgia naturally.
- Reference a real prior stay pattern if available.
- Invite the guest back with a soft high-touch CTA.
- No placeholders. No markdown. No bullets."""

    text, _model = await _call_llm(
        system,
        user,
        model=HYDRA_MODEL_120B,
        base_url=HYDRA_120B_URL,
        temperature=0.6,
        max_tokens=420,
    )
    draft = (text or "").strip()
    return draft[:1600] if draft else ""


async def draft_reactivation_sequence(
    db: AsyncSession,
    *,
    guest_id: UUID,
    target_score: int,
    trigger_type: str = "EVENT_CONSUMER_REACTIVATION_DISPATCHED",
) -> dict[str, Any]:
    guest = await db.get(Guest, guest_id)
    if guest is None:
        raise ValueError(f"guest_id not found: {guest_id}")
    if guest.is_blacklisted:
        raise ValueError("Guest is blacklisted; reactivation outreach blocked.")
    if guest.is_do_not_contact:
        raise ValueError("Guest is marked do_not_contact; reactivation outreach blocked.")

    reservation_rows = (
        await db.execute(
            select(Reservation, Property)
            .outerjoin(Property, Property.id == Reservation.property_id)
            .where(Reservation.guest_id == guest.id)
            .order_by(Reservation.check_out_date.desc(), Reservation.created_at.desc())
            .limit(8)
        )
    ).all()
    reservations = [
        _reservation_snapshot(reservation, prop)
        for reservation, prop in reservation_rows
    ]

    message_rows = (
        await db.execute(
            select(Message)
            .where(Message.guest_id == guest.id)
            .order_by(Message.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    recent_messages = [_message_snapshot(message) for message in reversed(message_rows)]

    favorite_property = _favorite_property(reservations)
    favorite_property_id = favorite_property.get("property_id") if favorite_property else None
    signals = _behavioral_signals(guest, reservations)
    delivery_channel = _initial_delivery_channel(guest)
    draft = await _generate_draft(
        guest=guest,
        target_score=target_score,
        reservations=reservations,
        recent_messages=recent_messages,
        favorite_property=favorite_property,
        signals=signals,
    )
    if not draft:
        draft = _fallback_draft(
            guest,
            favorite_property.get("property_name") if favorite_property else None,
        )

    queue_entry = AgentQueue(
        guest_id=guest.id,
        property_id=UUID(str(favorite_property_id)) if favorite_property_id else None,
        original_ai_draft=draft,
        status="pending_review",
        delivery_channel=delivery_channel,
    )
    db.add(queue_entry)
    await db.flush()

    logger.info(
        "hunter_reactivation_draft_queued",
        guest_id=str(guest.id),
        queue_entry_id=str(queue_entry.id),
        target_score=target_score,
        trigger_type=trigger_type,
    )

    return {
        "workflow": "draft_reactivation_sequence",
        "guest": {
            "id": str(guest.id),
            "full_name": guest.full_name,
            "email": guest.email,
            "last_stay_date": guest.last_stay_date.isoformat() if guest.last_stay_date else None,
            "lifetime_value": float(guest.lifetime_revenue or 0),
        },
        "favorite_property": favorite_property,
        "signals": signals,
        "target_score": target_score,
        "draft_reply": {
            "text": draft,
            "is_draft": True,
            "channel": delivery_channel,
        },
        "queue_entry": {
            "id": str(queue_entry.id),
            "status": queue_entry.status,
            "delivery_channel": queue_entry.delivery_channel,
        },
        "trigger_type": trigger_type,
    }
