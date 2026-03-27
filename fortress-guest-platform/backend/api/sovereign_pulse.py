"""
Sovereign Pulse — Command Center aggregate for DGX fleet posture, SEO Tribunal queue,
and direct-booking handshake ledger convergence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models import Property, Reservation, SEOPatch
from backend.models.reservation_hold import ReservationHold
from backend.models.staff import StaffRole, StaffUser

router = APIRouter()

PULSE_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])


class HandshakeConvergencePayload(BaseModel):
    """Stripe ↔ reservation_holds ↔ reservations integrity snapshot."""

    holds_active: int = Field(description="Checkout holds currently in active state")
    holds_converted_last_24h: int
    direct_reservations_last_24h: int
    orphan_risk_holds: int = Field(
        description="Active holds past expiry that still reference a PaymentIntent (manual review)"
    )
    holds_with_conversion_fk: int = Field(
        description="Converted holds that record converted_reservation_id (hardened handshake)"
    )
    holds_converted_legacy_no_fk: int = Field(
        description="Converted holds missing converted_reservation_id (pre-migration rows)"
    )
    as_of: datetime


class SeoQueueStatusPayload(BaseModel):
    drafted: int
    needs_rewrite: int
    pending_human: int
    deployed: int
    rejected: int
    total: int


class TribunalPatchRow(BaseModel):
    patch_id: UUID
    property_slug: str | None
    property_name: str | None
    page_path: str
    godhead_score: float | None
    godhead_model: str | None
    updated_at: datetime
    media_gallery_in_source: bool = Field(
        default=False,
        description="Heuristic: extraction snapshot included media_gallery context",
    )


class GodHeadTribunalPayload(BaseModel):
    godhead_pass_threshold: float
    pending_human_at_or_above_threshold: int
    pending_human_below_threshold: int
    pending_human_score_unknown: int
    recent_pending_human: list[TribunalPatchRow]
    fleet_target_properties: int = Field(
        default=16,
        description="Operational target for re-extraction wave (documentation / UI anchor)",
    )


class SovereignPulsePayload(BaseModel):
    handshake: HandshakeConvergencePayload
    seo_queue: SeoQueueStatusPayload
    tribunal: GodHeadTribunalPayload
    generated_at: datetime


def _media_gallery_hint(patch: SEOPatch) -> bool:
    fb = patch.godhead_feedback if isinstance(patch.godhead_feedback, dict) else {}
    if fb.get("media_gallery_context") or fb.get("has_media_gallery"):
        return True
    # Proposals sometimes stash extraction hints on rubric feedback keys
    if isinstance(fb.get("source_snapshot"), dict) and fb["source_snapshot"].get("media_gallery"):
        return True
    return False


async def build_sovereign_pulse_payload(db: AsyncSession) -> SovereignPulsePayload:
    """Shared builder for `/sovereign-pulse` and staff dashboard telemetry."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    threshold = float(settings.seo_godhead_min_score)

    # --- SEO queue (all statuses) ---
    rows = (await db.execute(select(SEOPatch.status, func.count(SEOPatch.id)).group_by(SEOPatch.status))).all()
    counts: dict[str, int] = {str(s): int(c) for s, c in rows}
    seo_queue = SeoQueueStatusPayload(
        drafted=counts.get("drafted", 0),
        needs_rewrite=counts.get("needs_rewrite", 0),
        pending_human=counts.get("pending_human", 0),
        deployed=counts.get("deployed", 0),
        rejected=counts.get("rejected", 0),
        total=sum(counts.values()),
    )

    # --- Tribunal: pending_human score bands ---
    ph_at = (
        await db.execute(
            select(func.count())
            .select_from(SEOPatch)
            .where(
                SEOPatch.status == "pending_human",
                SEOPatch.godhead_score.is_not(None),
                SEOPatch.godhead_score >= threshold,
            )
        )
    ).scalar_one()
    ph_below = (
        await db.execute(
            select(func.count())
            .select_from(SEOPatch)
            .where(
                SEOPatch.status == "pending_human",
                SEOPatch.godhead_score.is_not(None),
                SEOPatch.godhead_score < threshold,
            )
        )
    ).scalar_one()
    ph_unknown = (
        await db.execute(
            select(func.count())
            .select_from(SEOPatch)
            .where(SEOPatch.status == "pending_human", SEOPatch.godhead_score.is_(None))
        )
    ).scalar_one()

    recent_q = (
        await db.execute(
            select(SEOPatch, Property.slug, Property.name)
            .outerjoin(Property, SEOPatch.property_id == Property.id)
            .where(SEOPatch.status == "pending_human")
            .order_by(SEOPatch.updated_at.desc())
            .limit(24)
        )
    ).all()

    recent_rows: list[TribunalPatchRow] = []
    for patch, prop_slug, prop_name in recent_q:
        recent_rows.append(
            TribunalPatchRow(
                patch_id=patch.id,
                property_slug=prop_slug,
                property_name=prop_name,
                page_path=patch.page_path,
                godhead_score=patch.godhead_score,
                godhead_model=patch.godhead_model,
                updated_at=patch.updated_at,
                media_gallery_in_source=_media_gallery_hint(patch),
            )
        )

    tribunal = GodHeadTribunalPayload(
        godhead_pass_threshold=threshold,
        pending_human_at_or_above_threshold=int(ph_at or 0),
        pending_human_below_threshold=int(ph_below or 0),
        pending_human_score_unknown=int(ph_unknown or 0),
        recent_pending_human=recent_rows,
        fleet_target_properties=16,
    )

    # --- Handshake ledger ---
    holds_active = (
        await db.execute(
            select(func.count()).select_from(ReservationHold).where(ReservationHold.status == "active")
        )
    ).scalar_one()
    holds_converted_24h = (
        await db.execute(
            select(func.count())
            .select_from(ReservationHold)
            .where(
                ReservationHold.status == "converted",
                ReservationHold.updated_at >= window_start,
            )
        )
    ).scalar_one()
    direct_res_24h = (
        await db.execute(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.booking_source == "direct",
                Reservation.created_at >= window_start,
            )
        )
    ).scalar_one()

    orphan_risk = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ReservationHold)
                .where(
                    ReservationHold.status == "active",
                    ReservationHold.expires_at < now,
                    ReservationHold.payment_intent_id.is_not(None),
                )
            )
        ).scalar_one()
        or 0
    )

    with_fk = 0
    legacy_conv = 0
    try:
        with_fk = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ReservationHold)
                    .where(
                        ReservationHold.status == "converted",
                        ReservationHold.converted_reservation_id.is_not(None),
                    )
                )
            ).scalar_one()
            or 0
        )
        legacy_conv = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ReservationHold)
                    .where(
                        ReservationHold.status == "converted",
                        ReservationHold.converted_reservation_id.is_(None),
                    )
                )
            ).scalar_one()
            or 0
        )
    except ProgrammingError:
        await db.rollback()
        with_fk = 0
        legacy_conv = 0

    handshake = HandshakeConvergencePayload(
        holds_active=int(holds_active or 0),
        holds_converted_last_24h=int(holds_converted_24h or 0),
        direct_reservations_last_24h=int(direct_res_24h or 0),
        orphan_risk_holds=orphan_risk,
        holds_with_conversion_fk=with_fk,
        holds_converted_legacy_no_fk=legacy_conv,
        as_of=now,
    )

    return SovereignPulsePayload(
        handshake=handshake,
        seo_queue=seo_queue,
        tribunal=tribunal,
        generated_at=now,
    )


@router.get(
    "/sovereign-pulse",
    response_model=SovereignPulsePayload,
    summary="Sovereign Pulse — ledger + SEO Tribunal + handshake metrics",
)
async def get_sovereign_pulse(
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
) -> SovereignPulsePayload:
    return await build_sovereign_pulse_payload(db)
