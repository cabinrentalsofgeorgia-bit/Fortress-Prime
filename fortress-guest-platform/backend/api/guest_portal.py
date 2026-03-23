from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from backend.core.guest_security import AuthenticatedGuest, get_current_guest
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.guest_security import CONVERTED_RESERVATION_STATUSES, create_guest_token
from backend.core.security import require_admin
from backend.models.guestbook import GuestbookGuide
from backend.models.media import PROPERTY_IMAGE_STATUS_INGESTED, PropertyImage
from backend.models.property import Property
from backend.models.reservation import Reservation

router = APIRouter()

KNOWLEDGE_CATEGORIES = frozenset({"wifi", "access", "arrival", "parking", "rules", "amenities"})
GUEST_PORTAL_LINK_TTL = timedelta(days=7)


class GuestPortalReservationPayload(BaseModel):
    id: str
    confirmation_code: str
    guest_name: str
    guest_email: str
    status: str
    check_in_date: str
    check_out_date: str
    num_guests: int


class GuestPortalPropertyPayload(BaseModel):
    id: str
    name: str
    address: str | None = None
    hero_image_url: str | None = None


class GuestPortalWifiPayload(BaseModel):
    ssid: str | None = None
    password: str | None = None


class GuestPortalAccessPayload(BaseModel):
    code: str | None = None
    code_valid_from: str | None = None
    code_valid_until: str | None = None
    access_code_type: str | None = None
    access_code_location: str | None = None


class GuestPortalKnowledgeSnippetPayload(BaseModel):
    title: str
    category: str
    content: str


class GuestPortalKnowledgePayload(BaseModel):
    wifi: GuestPortalWifiPayload
    access: GuestPortalAccessPayload
    parking_instructions: str | None = None
    snippets: list[GuestPortalKnowledgeSnippetPayload] = Field(default_factory=list)


class GuestPortalItineraryPayload(BaseModel):
    reservation: GuestPortalReservationPayload
    property: GuestPortalPropertyPayload
    knowledge: GuestPortalKnowledgePayload
    stay_phase: Literal["pre_arrival", "during_stay", "post_checkout"]


class GuestPortalAdminLinkPayload(BaseModel):
    reservation_id: str
    confirmation_code: str
    property_id: str
    property_name: str
    guest_email: str
    status: str
    expires_at: str
    token: str
    portal_url: str
    local_portal_url: str


def _resolve_stay_phase(reservation: Reservation) -> Literal["pre_arrival", "during_stay", "post_checkout"]:
    today = Reservation._et_today()
    if today < reservation.check_in_date:
        return "pre_arrival"
    if today <= reservation.check_out_date:
        return "during_stay"
    return "post_checkout"


def _resolve_hero_image_url(property_record: Property) -> str | None:
    hero_candidate: PropertyImage | None = None
    for image in property_record.images:
        if image.is_hero:
            hero_candidate = image
            break
    hero_image = hero_candidate or (property_record.images[0] if property_record.images else None)
    if hero_image is None:
        return None
    if hero_image.status != PROPERTY_IMAGE_STATUS_INGESTED:
        return None
    return (hero_image.sovereign_url or "").strip() or None


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _guide_is_visible(guide: GuestbookGuide) -> bool:
    return bool(guide.is_visible)


def _guide_matches_localized_categories(guide: GuestbookGuide) -> bool:
    category = (guide.category or "").strip().lower()
    guide_type = (guide.guide_type or "").strip().lower()
    return category in KNOWLEDGE_CATEGORIES or guide_type == "home_guide"


async def _load_portal_reservation(
    db: AsyncSession,
    reservation_id: UUID,
) -> Reservation:
    result = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.guest),
            joinedload(Reservation.prop).selectinload(Property.images),
            joinedload(Reservation.prop).selectinload(Property.guestbook_guides),
        )
        .where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status not in CONVERTED_RESERVATION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Guest portal links can only be minted for converted reservations",
        )
    if reservation.prop is None or reservation.guest is None:
        raise HTTPException(
            status_code=409,
            detail="Reservation is missing required guest or property context",
        )
    return reservation


@router.get("/itinerary", response_model=GuestPortalItineraryPayload)
async def get_guest_itinerary(
    current_guest: AuthenticatedGuest = Depends(get_current_guest),
) -> GuestPortalItineraryPayload:
    reservation = current_guest.reservation
    property_record = current_guest.property
    stay_phase = _resolve_stay_phase(reservation)

    snippets = [
        GuestPortalKnowledgeSnippetPayload(
            title=guide.title,
            category=(guide.category or guide.guide_type or "guide").strip().lower() or "guide",
            content=guide.content,
        )
        for guide in property_record.guestbook_guides
        if _guide_is_visible(guide) and _guide_matches_localized_categories(guide)
    ]
    snippets.sort(key=lambda guide: (guide.category, guide.title))

    return GuestPortalItineraryPayload(
        reservation=GuestPortalReservationPayload(
            id=str(reservation.id),
            confirmation_code=reservation.confirmation_code,
            guest_name=reservation.guest.full_name,
            guest_email=reservation.guest.email,
            status=reservation.status,
            check_in_date=reservation.check_in_date.isoformat(),
            check_out_date=reservation.check_out_date.isoformat(),
            num_guests=reservation.num_guests,
        ),
        property=GuestPortalPropertyPayload(
            id=str(property_record.id),
            name=property_record.name,
            address=property_record.address,
            hero_image_url=_resolve_hero_image_url(property_record),
        ),
        knowledge=GuestPortalKnowledgePayload(
            wifi=GuestPortalWifiPayload(
                ssid=property_record.wifi_ssid,
                password=property_record.wifi_password,
            ),
            access=GuestPortalAccessPayload(
                code=reservation.access_code,
                code_valid_from=_serialize_timestamp(reservation.access_code_valid_from),
                code_valid_until=_serialize_timestamp(reservation.access_code_valid_until),
                access_code_type=property_record.access_code_type,
                access_code_location=property_record.access_code_location,
            ),
            parking_instructions=property_record.parking_instructions,
            snippets=snippets,
        ),
        stay_phase=stay_phase,
    )


@router.post("/admin/link/{reservation_id}", response_model=GuestPortalAdminLinkPayload)
async def mint_guest_portal_link(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
) -> GuestPortalAdminLinkPayload:
    reservation = await _load_portal_reservation(db, reservation_id)
    token = create_guest_token(str(reservation.id), expires_delta=GUEST_PORTAL_LINK_TTL)
    expires_at = datetime.now(timezone.utc) + GUEST_PORTAL_LINK_TTL
    storefront_base = settings.storefront_base_url.rstrip("/")
    local_base = "http://127.0.0.1:3000"
    token_query = f"/itinerary?token={token}"

    return GuestPortalAdminLinkPayload(
        reservation_id=str(reservation.id),
        confirmation_code=reservation.confirmation_code,
        property_id=str(reservation.prop.id),
        property_name=reservation.prop.name,
        guest_email=reservation.guest.email,
        status=reservation.status,
        expires_at=expires_at.isoformat(),
        token=token,
        portal_url=f"{storefront_base}{token_query}",
        local_portal_url=f"{local_base}{token_query}",
    )
