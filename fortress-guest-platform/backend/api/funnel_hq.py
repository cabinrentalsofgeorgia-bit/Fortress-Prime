"""
Strike 10 — Funnel heatmap + Recovery HQ (staff-only telemetry).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.staff import StaffRole, StaffUser
from backend.services.enticer_swarm_service import (
    get_concierge_book_url,
    get_effective_recovery_template,
    render_recovery_sms_body,
)
from backend.services.funnel_analytics_service import build_funnel_hq_payload

router = APIRouter()

FUNNEL_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])


class FunnelEdgePayload(BaseModel):
    from_stage: str
    to_stage: str
    from_label: str
    to_label: str
    from_count: int
    to_count: int
    retention_pct: float | None = None
    leakage_pct: float | None = None


class RecoveryRowPayload(BaseModel):
    session_fp_suffix: str
    session_fp: str
    last_event_type: str
    last_seen_at: datetime
    intent_score_estimate: float
    deepest_funnel_stage: str
    friction_label: str
    linked_guest_id: UUID | None = None
    property_slug: str | None = None
    drop_off_point: str
    drop_off_point_label: str
    guest_email: str | None = None
    guest_phone: str | None = None
    guest_display_name: str | None = None


class EnticementForgePayload(BaseModel):
    """Preview of Enticer Swarm SMS (Strike 11) — staff-only."""

    sms_enabled: bool = Field(description="CONCIERGE_RECOVERY_SMS_ENABLED")
    cooldown_hours: int
    book_url: str
    template_raw: str
    sample_rendered_body: str
    twilio_configured: bool


class FunnelHQPayload(BaseModel):
    window_hours: int
    distinct_sessions_in_window: int
    generated_at: datetime
    min_stale_minutes: int = 120
    edges: list[FunnelEdgePayload]
    recovery: list[RecoveryRowPayload]
    ledger_ready: bool = True
    enticement_forge: EnticementForgePayload


def _build_enticement_forge() -> EnticementForgePayload:
    book = get_concierge_book_url()
    twilio_ok = bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_phone_number
    )
    return EnticementForgePayload(
        sms_enabled=bool(getattr(settings, "concierge_recovery_sms_enabled", False)),
        cooldown_hours=int(getattr(settings, "concierge_recovery_sms_cooldown_hours", 168) or 168),
        book_url=book,
        template_raw=get_effective_recovery_template(),
        sample_rendered_body=render_recovery_sms_body(first_name="Jordan", book_url=book),
        twilio_configured=twilio_ok,
    )


@router.get(
    "/funnel-hq",
    response_model=FunnelHQPayload,
    summary="Funnel heatmap + high-intent recovery queue (Sovereign Pulse)",
)
async def get_funnel_hq(
    _: StaffUser = Depends(FUNNEL_ACCESS),
    db: AsyncSession = Depends(get_db),
    window_hours: int = Query(168, ge=1, le=24 * 90, description="Rolling lookback (hours)"),
    recovery_limit: int = Query(50, ge=1, le=200),
    stale_after_hours: int = Query(
        2,
        ge=1,
        le=168,
        description="Recovery candidates must be quiet for at least this many hours",
    ),
    min_stale_minutes: int | None = Query(
        None,
        ge=0,
        le=168 * 60,
        description="Override stale threshold in minutes. Use 0 for immediate pilot visibility.",
    ),
) -> FunnelHQPayload:
    try:
        raw = await build_funnel_hq_payload(
            db,
            window_hours=window_hours,
            recovery_limit=recovery_limit,
            stale_after_hours=stale_after_hours,
            min_stale_minutes=min_stale_minutes,
        )
    except ProgrammingError:
        await db.rollback()
        return FunnelHQPayload(
            window_hours=window_hours,
            distinct_sessions_in_window=0,
            generated_at=datetime.now(timezone.utc),
            min_stale_minutes=min_stale_minutes if min_stale_minutes is not None else stale_after_hours * 60,
            edges=[],
            recovery=[],
            ledger_ready=False,
            enticement_forge=_build_enticement_forge(),
        )

    return FunnelHQPayload(
        window_hours=int(raw["window_hours"]),
        distinct_sessions_in_window=int(raw["distinct_sessions_in_window"]),
        generated_at=raw["generated_at"],
        min_stale_minutes=int(raw.get("min_stale_minutes", stale_after_hours * 60)),
        edges=[FunnelEdgePayload(**e) for e in raw["edges"]],
        recovery=[RecoveryRowPayload(**r) for r in raw["recovery"]],
        ledger_ready=True,
        enticement_forge=_build_enticement_forge(),
    )
