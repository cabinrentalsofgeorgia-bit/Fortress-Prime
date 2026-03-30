"""
Link consented storefront session UUIDs to ledger guests after checkout hold creation.

PII is only written after the guest submits the booking form (Strike 10 identity bridge).
"""

from __future__ import annotations

import re
from uuid import UUID

import structlog
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.storefront_intent import _session_fingerprint
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.models.storefront_session_guest_link import StorefrontSessionGuestLink

logger = structlog.get_logger()

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")


async def record_hold_intent_bridge(
    db: AsyncSession,
    *,
    intent_session_id: UUID,
    guest_id: UUID,
    hold_id: UUID,
    property_slug: str | None,
) -> None:
    """
    Insert funnel_hold_started intent row + session↔guest link. Commits its own transaction
    fragment; safe after :func:`create_checkout_hold` (which already committed).
    """
    fp = _session_fingerprint(intent_session_id)
    raw = (property_slug or "").strip().lower()
    slug: str | None = None
    if raw and len(raw) <= 255 and _SLUG_OK.match(raw):
        slug = raw

    ev = StorefrontIntentEvent(
        session_fp=fp,
        event_type="funnel_hold_started",
        consent_marketing=True,
        property_slug=slug,
        meta={"hold_id": str(hold_id)},
    )
    link = StorefrontSessionGuestLink(
        session_fp=fp,
        guest_id=guest_id,
        reservation_hold_id=hold_id,
        source="checkout_hold",
    )
    try:
        db.add(ev)
        db.add(link)
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        logger.warning("funnel_identity_bridge_table_missing", error=str(exc)[:200])
    except Exception:
        await db.rollback()
        logger.exception("funnel_identity_bridge_failed")
