"""
Strike 11 — Enticer Swarm: recovery SMS for high-intent abandoned sessions with known guest.

Strike 17 — Active Pilot: live sends require ``CONCIERGE_STRIKE_ENABLED``, cohort allowlists,
and (by default) ``AGENTIC_SYSTEM_ACTIVE`` for instant rollback.

Respects ``CONCIERGE_RECOVERY_SMS_ENABLED`` and per-guest cooldown. Twilio keys must be set in env.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.integrations.twilio_client import TwilioClient
from backend.models.concierge_recovery_dispatch import ConciergeRecoveryDispatch
from backend.models.guest import Guest
from backend.services.funnel_analytics_service import build_funnel_hq_payload
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger()

DEFAULT_TEMPLATE = (
    "Cabin Rentals of Georgia: still planning your trip? Pick up your saved quote here: {book_url}"
)


def _parse_uuid_allowlist(raw: str) -> set[UUID]:
    out: set[UUID] = set()
    for part in (raw or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(UUID(p))
        except ValueError:
            logger.warning("enticer_strike_invalid_guest_uuid", fragment=p[:32])
    return out


def _parse_lower_csv_set(raw: str) -> set[str]:
    return {x.strip().lower() for x in (raw or "").split(",") if x.strip()}


def evaluate_concierge_strike17_eligibility(
    *,
    guest: Guest,
    property_slug: str | None,
) -> tuple[bool, str]:
    """
    AND across non-empty allowlist dimensions. All lists empty => fail closed (no sends).
    """
    guest_set = _parse_uuid_allowlist(settings.concierge_strike_allowed_guest_ids)
    slug_set = _parse_lower_csv_set(settings.concierge_strike_allowed_property_slugs)
    tier_set = _parse_lower_csv_set(settings.concierge_strike_allowed_loyalty_tiers)

    if not guest_set and not slug_set and not tier_set:
        return False, "no_cohort_configured"

    if guest_set and guest.id not in guest_set:
        return False, "guest_not_in_allowlist"

    if slug_set:
        slug = (property_slug or "").strip().lower()
        if not slug or slug not in slug_set:
            return False, "property_slug_not_in_allowlist"

    if tier_set:
        tier = (guest.loyalty_tier or "").strip().lower() or "bronze"
        if tier not in tier_set:
            return False, "loyalty_tier_not_in_allowlist"

    return True, "ok"


def get_effective_recovery_template() -> str:
    t = (getattr(settings, "concierge_recovery_sms_body_template", None) or "").strip()
    return t or DEFAULT_TEMPLATE


def get_concierge_book_url() -> str:
    return (
        (getattr(settings, "concierge_storefront_book_url", None) or "").strip()
        or "https://cabin-rentals-of-georgia.com/book"
    )


def render_recovery_sms_body(*, first_name: str, book_url: str | None = None) -> str:
    """Same interpolation the Enticer Swarm uses at send time."""
    url = book_url or get_concierge_book_url()
    return get_effective_recovery_template().format(book_url=url, first_name=first_name)


async def _recent_dispatch_exists(
    db: AsyncSession,
    *,
    guest_id: UUID,
    channel: str,
    template_key: str,
    since: datetime,
) -> bool:
    q = (
        select(ConciergeRecoveryDispatch.id)
        .where(
            ConciergeRecoveryDispatch.guest_id == guest_id,
            ConciergeRecoveryDispatch.channel == channel,
            ConciergeRecoveryDispatch.template_key == template_key,
            ConciergeRecoveryDispatch.created_at >= since,
            ConciergeRecoveryDispatch.status == "sent",
        )
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none() is not None


async def send_recovery_sms(
    db: AsyncSession,
    *,
    to_e164: str,
    body: str,
    guest_id: UUID,
    session_fp: str | None,
    template_key: str = "abandon_cart_v1",
) -> dict[str, Any]:
    """Persist dispatch row and send via Twilio. Caller must enforce cooldown."""
    client = TwilioClient()
    result = await client.send_sms(
        to=to_e164,
        body=body,
        status_callback=settings.twilio_status_callback_url or None,
    )
    row = ConciergeRecoveryDispatch(
        session_fp=session_fp,
        guest_id=guest_id,
        channel="sms",
        template_key=template_key,
        body_preview=body[:500],
        status="sent",
        provider_metadata={"twilio": {k: str(v) for k, v in (result or {}).items()}},
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "twilio_sid": result.get("sid")}


async def run_enticer_swarm_tick(
    db: AsyncSession,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """
    Process Funnel HQ recovery rows that already have a linked guest_id (concierge or hold path).

    Live Twilio sends run only when recovery SMS, Strike 17, Twilio, cohort allowlists,
    and (unless disabled in settings) AGENTIC_SYSTEM_ACTIVE are satisfied.
    """
    if not getattr(settings, "concierge_recovery_sms_enabled", False):
        logger.info("enticer_swarm_disabled")
        return [{"skipped": True, "reason": "CONCIERGE_RECOVERY_SMS_ENABLED=false"}]

    if not getattr(settings, "concierge_strike_enabled", False):
        logger.info("enticer_strike17_disabled")
        return [{"skipped": True, "reason": "CONCIERGE_STRIKE_ENABLED=false"}]

    if (
        getattr(settings, "concierge_strike_require_agentic_system_active", True)
        and not settings.agentic_system_active
    ):
        logger.info("enticer_strike17_agentic_inactive")
        return [{"skipped": True, "reason": "AGENTIC_SYSTEM_ACTIVE=false"}]

    if not (
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_phone_number
    ):
        logger.warning("enticer_swarm_twilio_not_configured")
        return [{"skipped": True, "reason": "twilio_not_configured"}]

    cooldown_h = int(getattr(settings, "concierge_recovery_sms_cooldown_hours", 168) or 168)
    since_cooldown = datetime.now(timezone.utc) - timedelta(hours=max(1, cooldown_h))
    book_url = get_concierge_book_url()

    raw = await build_funnel_hq_payload(db, window_hours=168, recovery_limit=80, stale_after_hours=2)
    recovery = raw.get("recovery") or []

    out: list[dict[str, Any]] = []
    processed = 0

    for row in recovery:
        if processed >= limit:
            break
        gid = row.get("linked_guest_id")
        if gid is None:
            continue
        if isinstance(gid, str):
            gid = UUID(gid)

        if await _recent_dispatch_exists(
            db,
            guest_id=gid,
            channel="sms",
            template_key="abandon_cart_v1",
            since=since_cooldown,
        ):
            continue

        guest = await db.get(Guest, gid)
        if guest is None or not guest.phone:
            out.append({"guest_id": str(gid), "skipped": True, "reason": "no_phone"})
            continue

        digits = "".join(c for c in (guest.phone or "") if c.isdigit())
        if len(digits) < 10:
            out.append({"guest_id": str(gid), "skipped": True, "reason": "invalid_phone"})
            continue
        if len(digits) == 10:
            to_e164 = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            to_e164 = f"+{digits}"
        else:
            to_e164 = f"+{digits}"

        pslug = row.get("property_slug")
        property_slug = str(pslug).strip().lower() if pslug else None

        ok, strike_reason = evaluate_concierge_strike17_eligibility(
            guest=guest,
            property_slug=property_slug,
        )
        if not ok:
            out.append({"guest_id": str(gid), "skipped": True, "reason": strike_reason})
            await record_audit_event(
                action="concierge_recovery_strike_skip",
                resource_type="concierge_strike17",
                resource_id=str(gid),
                outcome="blocked",
                metadata_json={
                    "reason": strike_reason,
                    "property_slug": property_slug,
                    "agentic_system_active": settings.agentic_system_active,
                },
            )
            continue

        body = render_recovery_sms_body(first_name=guest.first_name or "there", book_url=book_url)
        session_fp = row.get("session_fp")

        try:
            send_result = await send_recovery_sms(
                db,
                to_e164=to_e164,
                body=body,
                guest_id=gid,
                session_fp=str(session_fp) if session_fp else None,
            )
            processed += 1
            out.append({"guest_id": str(gid), "sent": True, **send_result})
            await record_audit_event(
                action="concierge_recovery_strike_sent",
                resource_type="concierge_strike17",
                resource_id=str(gid),
                outcome="success",
                metadata_json={
                    "template_key": "abandon_cart_v1",
                    "property_slug": property_slug,
                    "twilio_sid": send_result.get("twilio_sid"),
                },
            )
        except Exception as exc:
            await db.rollback()
            logger.error("enticer_swarm_send_failed", guest_id=str(gid), error=str(exc))
            out.append({"guest_id": str(gid), "error": str(exc)[:200]})
            await record_audit_event(
                action="concierge_recovery_strike_send_failed",
                resource_type="concierge_strike17",
                resource_id=str(gid),
                outcome="error",
                metadata_json={"error": str(exc)[:500], "property_slug": property_slug},
            )

    return out
