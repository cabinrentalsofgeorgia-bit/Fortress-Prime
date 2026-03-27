"""
Strike 11 — Consented storefront identity resolution (session_fp ↔ guest_id).

Only runs when the guest explicitly opts in to recovery contact. Never called without
``consent_recovery_contact=True`` (enforced by API).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.storefront_intent import _session_fingerprint
from backend.models.guest import Guest
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.models.storefront_session_guest_link import StorefrontSessionGuestLink

logger = structlog.get_logger()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
Flow = Literal["save_quote", "booking_field_blur"]


@dataclass(frozen=True)
class ResolveOutcome:
    linked: bool
    guest_id: UUID | None
    created_guest: bool


def _norm_email(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if not s or len(s) > 255:
        return None
    return s if _EMAIL_RE.match(s) else None


def _norm_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return digits


def _slug_ok(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if not s or len(s) > 255:
        return None
    return s if re.match(r"^[a-z0-9][a-z0-9-]*$", s) else None


async def _find_guest_by_contact(
    db: AsyncSession, *, email: str | None, phone: str | None
) -> Guest | None:
    if email:
        g = (await db.execute(select(Guest).where(Guest.email == email))).scalar_one_or_none()
        if g is not None:
            return g
    if phone:
        g = (await db.execute(select(Guest).where(Guest.phone == phone))).scalar_one_or_none()
        if g is not None:
            return g
    return None


async def _ensure_link(
    db: AsyncSession,
    *,
    session_fp: str,
    guest_id: UUID,
    source: str,
) -> None:
    existing = (
        await db.execute(
            select(StorefrontSessionGuestLink.id).where(
                StorefrontSessionGuestLink.session_fp == session_fp,
                StorefrontSessionGuestLink.guest_id == guest_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        StorefrontSessionGuestLink(
            session_fp=session_fp,
            guest_id=guest_id,
            reservation_hold_id=None,
            source=source,
        )
    )


async def resolve_session_identity(
    db: AsyncSession,
    *,
    session_id: UUID,
    consent_recovery_contact: bool,
    flow: Flow,
    email: str | None,
    phone: str | None,
    guest_first_name: str | None,
    guest_last_name: str | None,
    property_slug: str | None,
) -> ResolveOutcome:
    if not consent_recovery_contact:
        return ResolveOutcome(linked=False, guest_id=None, created_guest=False)

    email_n = _norm_email(email)
    phone_n = _norm_phone(phone)
    if not email_n and not phone_n:
        return ResolveOutcome(linked=False, guest_id=None, created_guest=False)

    fp = _session_fingerprint(session_id)
    slug = _slug_ok(property_slug)

    guest = await _find_guest_by_contact(db, email=email_n, phone=phone_n)
    created = False

    allow_create = flow == "save_quote" or flow == "booking_field_blur"
    fn = (guest_first_name or "").strip()[:100] or ""
    ln = (guest_last_name or "").strip()[:100] or ""

    if guest is None and allow_create and email_n:
        if not fn or not ln:
            if flow == "save_quote":
                return ResolveOutcome(linked=False, guest_id=None, created_guest=False)
            return ResolveOutcome(linked=False, guest_id=None, created_guest=False)
        candidate = Guest(
            email=email_n,
            first_name=fn or "Guest",
            last_name=ln or "Prospect",
            phone=phone_n,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
        except IntegrityError:
            guest = await _find_guest_by_contact(db, email=email_n, phone=phone_n)
        else:
            guest = candidate
            created = True

    if guest is None:
        return ResolveOutcome(linked=False, guest_id=None, created_guest=False)

    await _ensure_link(db, session_fp=fp, guest_id=guest.id, source="concierge_resolve")

    db.add(
        StorefrontIntentEvent(
            session_fp=fp,
            event_type="concierge_identity_resolved",
            consent_marketing=True,
            property_slug=slug,
            meta={"flow": flow, "guest_id": str(guest.id), "created": created},
        )
    )
    await db.commit()

    logger.info(
        "concierge_identity_resolved",
        flow=flow,
        created_guest=created,
        guest_id=str(guest.id),
    )
    return ResolveOutcome(linked=True, guest_id=guest.id, created_guest=created)
