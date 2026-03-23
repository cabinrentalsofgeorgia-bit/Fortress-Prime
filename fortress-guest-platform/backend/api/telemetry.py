"""Telemetry aggregation API for the Fortress Prime command dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.message import Message
from backend.models.reservation_hold import ReservationHold
from backend.models.seo_patch import SEOPatch
from backend.models.staff import StaffRole, StaffUser

router = APIRouter()


class AgentStatusPayload(BaseModel):
    concierge: str
    seo_swarm: str
    yield_engine: str


class RecentCommunicationPayload(BaseModel):
    id: str
    direction: str
    phone_number: str
    snippet: str
    timestamp: datetime


class TelemetryDashboardPayload(BaseModel):
    seo_queue_depth: int
    seo_deploy_queue_depth: int
    seo_failed_deploys: int
    seo_last_deploy_success_at: datetime | None = None
    seo_last_deploy_failure_at: datetime | None = None
    recent_comms: list[RecentCommunicationPayload]
    active_holds: int
    agent_status: AgentStatusPayload


@router.get(
    "/dashboard",
    response_model=TelemetryDashboardPayload,
)
async def get_telemetry_dashboard(
    _: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])),
    db: AsyncSession = Depends(get_db),
) -> TelemetryDashboardPayload:
    seo_queue_depth_result = await db.execute(
        select(func.count()).select_from(SEOPatch).where(SEOPatch.status == "pending_human")
    )
    seo_queue_depth = int(seo_queue_depth_result.scalar_one() or 0)
    seo_deploy_queue_depth_result = await db.execute(
        select(func.count())
        .select_from(SEOPatch)
        .where(SEOPatch.deploy_status.in_(("queued", "processing")))
    )
    seo_deploy_queue_depth = int(seo_deploy_queue_depth_result.scalar_one() or 0)
    seo_failed_deploys_result = await db.execute(
        select(func.count()).select_from(SEOPatch).where(SEOPatch.deploy_status == "failed")
    )
    seo_failed_deploys = int(seo_failed_deploys_result.scalar_one() or 0)
    seo_last_deploy_success_at = (
        await db.execute(
            select(func.max(SEOPatch.deploy_acknowledged_at)).where(SEOPatch.deploy_status == "succeeded")
        )
    ).scalar_one_or_none()
    seo_last_deploy_failure_at = (
        await db.execute(
            select(func.max(SEOPatch.deploy_acknowledged_at)).where(SEOPatch.deploy_status == "failed")
        )
    ).scalar_one_or_none()

    recent_comms_result = await db.execute(
        select(Message)
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    recent_messages = list(recent_comms_result.scalars().all())

    hold_window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    active_holds_result = await db.execute(
        select(func.count())
        .select_from(ReservationHold)
        .where(
            ReservationHold.created_at >= hold_window_start,
            ReservationHold.status != "converted",
        )
    )
    active_holds = int(active_holds_result.scalar_one() or 0)

    if seo_failed_deploys > 0:
        seo_swarm_status = "degraded"
    elif seo_deploy_queue_depth > 0:
        seo_swarm_status = "processing"
    elif seo_last_deploy_success_at and seo_last_deploy_success_at >= datetime.now(timezone.utc) - timedelta(hours=1):
        seo_swarm_status = "online"
    else:
        seo_swarm_status = "idle"

    return TelemetryDashboardPayload(
        seo_queue_depth=seo_queue_depth,
        seo_deploy_queue_depth=seo_deploy_queue_depth,
        seo_failed_deploys=seo_failed_deploys,
        seo_last_deploy_success_at=seo_last_deploy_success_at,
        seo_last_deploy_failure_at=seo_last_deploy_failure_at,
        recent_comms=[
            RecentCommunicationPayload(
                id=str(message.id),
                direction=message.direction,
                phone_number=message.phone_from if message.direction == "inbound" else message.phone_to,
                snippet=(message.body or "").strip()[:140],
                timestamp=message.created_at,
            )
            for message in recent_messages
        ],
        active_holds=active_holds,
        agent_status=AgentStatusPayload(
            concierge="online",
            seo_swarm=seo_swarm_status,
            yield_engine="online",
        ),
    )
