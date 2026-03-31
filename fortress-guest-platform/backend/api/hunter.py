from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import asyncio
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.models.agent_queue import AgentQueue
from backend.core.security import require_manager_or_admin, require_operator_manager_admin
from backend.models.guest import Guest
from backend.models.staff import StaffUser
from backend.services.email_service import is_email_configured, send_email
from backend.services.message_service import MessageService
from backend.services.openshell_audit import record_audit_event
from backend.vrs.domain.automations import StreamlineEventPayload
from backend.vrs.infrastructure.event_bus import publish_vrs_event, queue_depth

router = APIRouter()

_TARGET_LIMIT = 50
_RAW_SCAN_LIMIT = 200
_MIN_LIFETIME_VALUE = Decimal("5000.00")
_MIN_DORMANCY_DAYS = 365


class TargetGuest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_id: str
    full_name: str
    email: str
    lifetime_value: float
    last_stay_date: date
    days_dormant: int
    target_score: int


class DispatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_id: str = Field(..., description="The UUID of the dormant guest.")
    full_name: str
    target_score: int = Field(..., ge=0, le=100)


class HunterDispatchAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    event_id: str
    message: str
    queue_depth: int
    queue_key: str


class HunterQueueGuest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    full_name: str
    email: str | None = None
    loyalty_tier: str | None = None
    lifetime_value: float | None = None
    last_stay_date: date | None = None


class HunterQueueProperty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    slug: str


class HunterQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    delivery_channel: str | None = None
    original_ai_draft: str
    final_human_message: str | None = None
    twilio_sid: str | None = None
    error_log: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    guest: HunterQueueGuest | None = None
    property: HunterQueueProperty | None = None


class HunterQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HunterQueueItem]
    total: int
    limit: int
    status_filter: str


class HunterQueueStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_review: int
    approved: int
    edited: int
    rejected: int
    sending: int
    delivered: int
    failed: int
    total: int


class HunterApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = "operator"
    channel: Literal["email", "sms"] = "email"


class HunterEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_human_message: str = Field(..., min_length=1, max_length=1600)
    reviewed_by: str = "operator"
    channel: Literal["email", "sms"] = "email"


class HunterRejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = "operator"
    reason: str | None = Field(default=None, max_length=500)


class HunterRetryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = "operator"
    channel: Literal["email", "sms"] = "email"


class HunterQueueActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    id: str
    status: str
    reviewed_by: str
    delivery_status: str | None = None
    delivery_channel: str | None = None


class HunterAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str = Field(..., min_length=1, max_length=120)
    resource_type: str = Field(default="hunter_console", min_length=1, max_length=80)
    resource_id: str | None = Field(default=None, max_length=200)
    outcome: str = Field(default="success", max_length=40)
    metadata_json: dict[str, object] = Field(default_factory=dict)


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _target_score(guest: Guest, *, revenue: float, days_dormant: int) -> int:
    revenue_score = min(55, round(revenue / 500))
    dormancy_score = min(30, days_dormant // 12)
    vip_bonus = 10 if guest.is_vip else 0
    loyalty_bonus = min(10, max(int(guest.lifetime_stays or guest.total_stays or 0), 0) * 2)
    contact_bonus = 5 if guest.opt_in_marketing else 0
    return _clamp_score(revenue_score + dormancy_score + vip_bonus + loyalty_bonus + contact_bonus)


def _queue_item_payload(entry: AgentQueue) -> HunterQueueItem:
    guest = entry.guest
    prop = entry.prop
    return HunterQueueItem(
        id=str(entry.id),
        status=entry.status,
        delivery_channel=entry.delivery_channel,
        original_ai_draft=entry.original_ai_draft,
        final_human_message=entry.final_human_message,
        twilio_sid=entry.twilio_sid,
        error_log=entry.error_log,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        updated_at=entry.updated_at.isoformat() if entry.updated_at else None,
        guest=(
            HunterQueueGuest(
                id=str(guest.id) if guest and guest.id else None,
                full_name=guest.full_name if guest else "Unknown guest",
                email=guest.email if guest else None,
                loyalty_tier=guest.loyalty_tier if guest else None,
                lifetime_value=float(guest.lifetime_revenue or 0) if guest else None,
                last_stay_date=guest.last_stay_date if guest else None,
            )
            if guest
            else None
        ),
        property=(
            HunterQueueProperty(
                id=str(prop.id) if prop and prop.id else None,
                name=prop.name,
                slug=prop.slug,
            )
            if prop
            else None
        ),
    )


async def _load_agent_queue_entry(db: AsyncSession, entry_id: str) -> AgentQueue:
    try:
        queue_uuid = UUID(str(entry_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Hunter queue entry not found") from exc
    entry = await db.get(
        AgentQueue,
        queue_uuid,
        options=(selectinload(AgentQueue.guest), selectinload(AgentQueue.prop)),
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Hunter queue entry not found")
    return entry


def _hunter_email_subject(entry: AgentQueue) -> str:
    guest_name = (entry.guest.full_name if entry.guest else "there").strip()
    first_name = guest_name.split()[0] if guest_name else "there"
    property_name = (entry.prop.name if entry.prop else "").strip()
    if property_name:
        return f"{first_name}, ready for another stay at {property_name}?"
    return f"{first_name}, ready for another North Georgia mountain stay?"


def _hunter_email_html(entry: AgentQueue, body: str) -> str:
    guest_name = (entry.guest.full_name if entry.guest else "there").strip() or "there"
    property_name = (entry.prop.name if entry.prop else "").strip()
    property_line = (
        f"<p style=\"margin:0 0 16px;color:#52525b;font-size:15px;line-height:1.6;\">"
        f"Your past stay at <strong>{property_name}</strong> is still part of the story we remember."
        f"</p>"
        if property_name
        else ""
    )
    body_html = "<br><br>".join(
        line.strip() for line in body.splitlines() if line.strip()
    )
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;margin:40px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr>
      <td style="background:#18181b;padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:600;letter-spacing:-0.025em;">
          Cabin Rentals of Georgia
        </h1>
      </td>
    </tr>
    <tr>
      <td style="padding:32px;">
        <h2 style="margin:0 0 8px;color:#18181b;font-size:18px;">Hi {guest_name},</h2>
        {property_line}
        <div style="color:#3f3f46;font-size:15px;line-height:1.75;">{body_html}</div>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def _deliver_hunter_message(
    db: AsyncSession,
    entry: AgentQueue,
    body: str,
    channel: Literal["email", "sms"],
) -> tuple[bool, str | None]:
    guest = entry.guest
    if guest is None:
        return False, "Guest context is missing."

    if channel == "sms":
        entry.delivery_channel = "sms"
        if not (guest.phone_number or "").strip():
            return False, "Guest has no routable phone number."
        service = MessageService(db)
        try:
            message = await service.send_sms(
                to_phone=guest.phone_number,
                body=body,
                guest_id=guest.id,
                is_auto_response=True,
            )
            entry.twilio_sid = message.external_id
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:500]

    if not (guest.email or "").strip():
        return False, "Guest has no routable email address."
    if not is_email_configured():
        return False, "SMTP is not configured."

    entry.delivery_channel = "email"
    sent = await asyncio.to_thread(
        send_email,
        guest.email.strip(),
        _hunter_email_subject(entry),
        _hunter_email_html(entry, body),
        body,
    )
    if not sent:
        return False, "Email delivery returned false."
    entry.twilio_sid = None
    return True, None



class HunterHealthPayload(BaseModel):
    status: str
    service: str


class HunterQueueRowPayload(BaseModel):
    id: UUID
    session_fp: str
    property_id: UUID | None = None
    reservation_id: UUID | None = None
    guest_phone: str | None = None
    guest_email: str | None = None
    campaign: str
    payload: dict[str, Any] = Field(default_factory=dict)
    score: int
    status: str
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class HunterExecuteRequest(BaseModel):
    session_fp: str = Field(min_length=16, max_length=128)


class HunterExecuteResponse(BaseModel):
    status: str
    session_fp: str
    queue_status: str
    job_id: str


class HunterRecoveryOperationPayload(BaseModel):
    id: UUID
    cart_id: str
    guest_name: str | None = None
    cabin_name: str | None = None
    cart_value: float | None = None
    status: str
    ai_draft_body: str | None = None
    assigned_worker: str | None = None
    created_at: datetime


class HunterApproveResponse(BaseModel):
    status: str
    message: str
    channel: str


def _serialize_recovery_op(op: HunterRecoveryOp) -> HunterRecoveryOperationPayload:
    return HunterRecoveryOperationPayload(
        id=op.id,
        cart_id=op.cart_id,
        guest_name=op.guest_name,
        cabin_name=op.cabin_name,
        cart_value=float(op.cart_value) if op.cart_value is not None else None,
        status=op.status.value if isinstance(op.status, HunterRecoveryOpStatus) else str(op.status),
        ai_draft_body=op.ai_draft_body,
        assigned_worker=op.assigned_worker,
        created_at=op.created_at,
    )


async def _resolve_recovery_guest_contact(
    db: AsyncSession,
    *,
    cart_id: str,
) -> Guest | None:
    stmt = (
        select(Guest)
        .join(StorefrontSessionGuestLink, StorefrontSessionGuestLink.guest_id == Guest.id)
        .where(StorefrontSessionGuestLink.session_fp == cart_id)
        .order_by(StorefrontSessionGuestLink.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _dispatch_recovery_contact(
    *,
    guest: Guest,
    op: HunterRecoveryOp,
) -> str:
    draft_body = str(op.ai_draft_body or "").strip()
    if not draft_body:
        raise RuntimeError("Recovery draft body is empty.")

    if guest.email:
        subject = f"Your stay at {op.cabin_name or 'Cabin Rentals of Georgia'}"
        service = CommunicationService()
        await service.dispatch_email_reply(
            to_email=guest.email,
            subject=subject,
            message_body=draft_body,
        )
        return "email"

    if guest.phone:
        twilio = TwilioClient()
        await twilio.send_sms(to=guest.phone, body=draft_body)
        return "sms"

    raise RuntimeError("Guest contact record has no email or phone.")


def _normalize_status_filter(status_filter: str | None) -> tuple[str, ...] | None:
    if status_filter is None:
        return None
    normalized = status_filter.strip().lower()
    if not normalized:
        return None
    statuses = _STATUS_FILTER_ALIASES.get(normalized)
    if statuses is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_hunter_status_filter",
                "allowed": sorted(_STATUS_FILTER_ALIASES.keys()),
            },
        )
    return statuses


def _serialize_queue_entry(entry: HunterQueueEntry) -> HunterQueueRowPayload:
    return HunterQueueRowPayload(
        id=entry.id,
        session_fp=entry.session_fp,
        property_id=entry.property_id,
        reservation_id=entry.reservation_id,
        guest_phone=entry.guest_phone,
        guest_email=entry.guest_email,
        campaign=entry.campaign,
        payload=entry.payload or {},
        score=entry.score,
        status=entry.status,
        last_error=entry.last_error,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/hunter/health", response_model=HunterHealthPayload)
async def hunter_health(_: StaffUser = Depends(PULSE_ACCESS)):
    return HunterHealthPayload(status="ok", service="hunter")


@router.get("/hunter/queue", response_model=list[HunterQueueRowPayload])
async def hunter_queue(
    status_filter: str | None = Query(
        default=None,
        description="Queue status filter. Supports queued/processing/sent/failed/cancelled plus active and pending_review aliases.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
):
    statuses = _normalize_status_filter(status_filter)
    stmt = select(HunterQueueEntry).order_by(HunterQueueEntry.created_at.desc()).limit(limit)
    if statuses:
        stmt = stmt.where(HunterQueueEntry.status.in_(statuses))

    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_queue_entry(row) for row in rows]


@router.get("/hunter/operations", response_model=list[HunterRecoveryOperationPayload])
async def hunter_operations(
    limit: int = Query(default=100, ge=1, le=200),
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HunterRecoveryOp).order_by(HunterRecoveryOp.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_recovery_op(row) for row in rows]


@router.post(
    "/hunter/execute",
    response_model=HunterExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_hunter_candidate_route(
    body: HunterExecuteRequest,
    user: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
):
    session_fp = body.session_fp.strip().lower()
    entry = (
        await db.execute(
            select(HunterQueueEntry).where(HunterQueueEntry.session_fp == session_fp).limit(1)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hunter candidate not found")
    if entry.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hunter candidate is already processing",
        )

    job = await enqueue_async_job(
        db,
        worker_name="run_hunter_execute_job",
        job_name="hunter_execute",
        payload={"session_fp": session_fp},
        requested_by=user.email,
        tenant_id=None,
        request_id=f"hunter-execute:{session_fp[:12]}",
    )
    entry.status = "processing"
    entry.last_error = None
    await db.commit()

    return HunterExecuteResponse(
        status="queued",
        session_fp=session_fp,
        queue_status=entry.status,
        job_id=str(job.id),
    )


@router.delete("/hunter/queue/{session_fp}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_hunter_candidate_route(
    session_fp: str,
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_hunter_candidate(db, session_fp.strip().lower())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hunter candidate not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/hunter/approve/{op_id}", response_model=HunterApproveResponse)
async def approve_and_dispatch_recovery(
    op_id: UUID,
    user: StaffUser = Depends(CONTROL_ACCESS),
    db: AsyncSession = Depends(get_db),
):
    op = await db.get(HunterRecoveryOp, op_id)
    if op is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found.")

    current_status = op.status if isinstance(op.status, HunterRecoveryOpStatus) else HunterRecoveryOpStatus(str(op.status))
    if current_status != HunterRecoveryOpStatus.DRAFT_READY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot dispatch. Current status: {current_status.value}",
        )

    guest = await _resolve_recovery_guest_contact(db, cart_id=op.cart_id)
    if guest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No consented guest contact could be resolved for this recovery operation.",
        )

    try:
        channel = await _dispatch_recovery_contact(guest=guest, op=op)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    op.status = HunterRecoveryOpStatus.DISPATCHED
    await db.commit()
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter_recovery_dispatch_approved",
        resource_type="hunter_recovery_op",
        resource_id=str(op.id),
        purpose="internal_revenue_recovery",
        tool_name=channel,
        outcome="success",
        request_id=f"hunter-approve:{str(op.id)[:12]}",
        metadata_json={
            "cart_id": op.cart_id,
            "channel": channel,
            "assigned_worker": op.assigned_worker,
        },
        db=db,
    )
    return HunterApproveResponse(
        status="success",
        message=f"Payload dispatched for Cart {op.cart_id}.",
        channel=channel,
    )


@router.get("/vrs/hunter/targets", response_model=list[TargetGuest])
async def get_reactivation_targets(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    """
    Returns dormant VIP-style guests suitable for Reactivation Hunter outreach.
    """

    today = date.today()
    dormant_cutoff = date.fromordinal(today.toordinal() - _MIN_DORMANCY_DAYS)

    result = await db.execute(
        select(Guest)
        .where(
            Guest.lifetime_revenue >= _MIN_LIFETIME_VALUE,
            Guest.last_stay_date.is_not(None),
            Guest.last_stay_date <= dormant_cutoff,
            Guest.is_blacklisted.is_(False),
            Guest.is_do_not_contact.is_(False),
        )
        .order_by(Guest.lifetime_revenue.desc(), Guest.last_stay_date.asc())
        .limit(_RAW_SCAN_LIMIT)
    )
    guests = result.scalars().all()

    targets: list[TargetGuest] = []
    for guest in guests:
        if guest.last_stay_date is None:
            continue

        email = (guest.email or "").strip()
        if not email:
            continue

        revenue = float(guest.lifetime_revenue or 0)
        days_dormant = (today - guest.last_stay_date).days
        targets.append(
            TargetGuest(
                guest_id=str(guest.id),
                full_name=guest.full_name,
                email=email,
                lifetime_value=revenue,
                last_stay_date=guest.last_stay_date,
                days_dormant=days_dormant,
                target_score=_target_score(guest, revenue=revenue, days_dormant=days_dormant),
            )
        )
        if len(targets) >= _TARGET_LIMIT:
            break

    return targets


@router.post(
    "/vrs/hunter/dispatch",
    response_model=HunterDispatchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_reactivation_agent(
    payload: DispatchPayload,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    """
    Enqueue a Reactivation Hunter dispatch event onto the canonical VRS Redis bus.
    """

    now = datetime.now(UTC)
    event = StreamlineEventPayload(
        entity_type="guest",
        entity_id=payload.guest_id,
        event_type="reactivation_dispatched",
        previous_state={},
        current_state={
            "guest_id": payload.guest_id,
            "full_name": payload.full_name,
            "target_score": payload.target_score,
            "event_id": f"hunter:{payload.guest_id}:{int(now.timestamp())}",
            "timestamp": now.isoformat(),
            "campaign": "reactivation_hunter",
            "source": "vrs_hunter_glass",
        },
    )

    queued = await publish_vrs_event(event)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Redis dispatch failed",
        )

    depth = await queue_depth()
    event_id = str(event.current_state.get("event_id") or "")
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter.dispatch",
        resource_type="hunter_target",
        resource_id=payload.guest_id,
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_dispatch",
        model_route="tool",
        outcome="success",
        metadata_json={
            "full_name": payload.full_name,
            "target_score": payload.target_score,
            "event_id": event_id,
            "queue_depth": depth,
        },
        db=db,
    )
    return HunterDispatchAccepted(
        status="queued",
        event_id=event_id,
        message=f"Agent dispatched for {payload.full_name}",
        queue_depth=depth,
        queue_key="fortress:events:streamline",
    )


@router.get("/vrs/hunter/queue", response_model=HunterQueueResponse)
async def list_hunter_queue(
    status_filter: str = Query(default="pending_review"),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    query = (
        select(AgentQueue)
        .options(selectinload(AgentQueue.guest), selectinload(AgentQueue.prop))
        .order_by(AgentQueue.created_at.desc())
    )
    count_query = select(func.count(AgentQueue.id))

    if status_filter != "all":
        query = query.where(AgentQueue.status == status_filter)
        count_query = count_query.where(AgentQueue.status == status_filter)

    total = int((await db.execute(count_query)).scalar() or 0)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return HunterQueueResponse(
        items=[_queue_item_payload(row) for row in rows],
        total=total,
        limit=limit,
        status_filter=status_filter,
    )


@router.get("/vrs/hunter/queue/stats", response_model=HunterQueueStats)
async def hunter_queue_stats(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    async def _count(status_value: str) -> int:
        return int(
            (await db.execute(select(func.count(AgentQueue.id)).where(AgentQueue.status == status_value))).scalar()
            or 0
        )

    pending_review = await _count("pending_review")
    approved = await _count("approved")
    edited = await _count("edited")
    rejected = await _count("rejected")
    sending = await _count("sending")
    delivered = await _count("delivered")
    failed = await _count("failed")
    total = pending_review + approved + edited + rejected + sending + delivered + failed
    return HunterQueueStats(
        pending_review=pending_review,
        approved=approved,
        edited=edited,
        rejected=rejected,
        sending=sending,
        delivered=delivered,
        failed=failed,
        total=total,
    )


@router.post(
    "/vrs/hunter/queue/{entry_id}/approve",
    response_model=HunterQueueActionResponse,
)
async def approve_hunter_queue_entry(
    entry_id: str,
    body: HunterApproveBody,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    entry = await _load_agent_queue_entry(db, entry_id)
    if entry.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Entry already {entry.status}")

    entry.status = "approved"
    entry.final_human_message = entry.final_human_message or entry.original_ai_draft
    body_to_send = entry.final_human_message or entry.original_ai_draft
    sent, error = await _deliver_hunter_message(db, entry, body_to_send, body.channel)
    entry.status = "delivered" if sent else "failed"
    entry.error_log = error
    await db.commit()
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter.queue.approve",
        resource_type="hunter_queue",
        resource_id=str(entry.id),
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_review",
        model_route="tool",
        outcome="success" if sent else "failed",
        metadata_json={
            "delivery_channel": body.channel,
            "delivery_status": "sent" if sent else "failed",
            "guest_id": str(getattr(entry, "guest_id", None)) if getattr(entry, "guest_id", None) else None,
        },
        db=db,
    )
    return HunterQueueActionResponse(
        ok=True,
        id=str(entry.id),
        status=entry.status,
        reviewed_by=body.reviewed_by,
        delivery_status="sent" if sent else "failed",
        delivery_channel=body.channel,
    )


@router.post(
    "/vrs/hunter/queue/{entry_id}/edit",
    response_model=HunterQueueActionResponse,
)
async def edit_hunter_queue_entry(
    entry_id: str,
    body: HunterEditBody,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    entry = await _load_agent_queue_entry(db, entry_id)
    if entry.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Entry already {entry.status}")

    entry.status = "edited"
    entry.final_human_message = body.final_human_message.strip()
    sent, error = await _deliver_hunter_message(
        db,
        entry,
        entry.final_human_message,
        body.channel,
    )
    entry.status = "delivered" if sent else "failed"
    entry.error_log = error
    await db.commit()
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter.queue.edit",
        resource_type="hunter_queue",
        resource_id=str(entry.id),
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_review",
        model_route="tool",
        outcome="success" if sent else "failed",
        metadata_json={
            "delivery_channel": body.channel,
            "delivery_status": "sent" if sent else "failed",
            "guest_id": str(getattr(entry, "guest_id", None)) if getattr(entry, "guest_id", None) else None,
        },
        db=db,
    )
    return HunterQueueActionResponse(
        ok=True,
        id=str(entry.id),
        status=entry.status,
        reviewed_by=body.reviewed_by,
        delivery_status="sent" if sent else "failed",
        delivery_channel=body.channel,
    )


@router.post(
    "/vrs/hunter/queue/{entry_id}/reject",
    response_model=HunterQueueActionResponse,
)
async def reject_hunter_queue_entry(
    entry_id: str,
    body: HunterRejectBody,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    entry = await _load_agent_queue_entry(db, entry_id)
    if entry.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Entry already {entry.status}")

    entry.status = "rejected"
    if body.reason:
        entry.error_log = body.reason.strip()
    await db.commit()
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter.queue.reject",
        resource_type="hunter_queue",
        resource_id=str(entry.id),
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_review",
        model_route="tool",
        outcome="success",
        metadata_json={
            "reason": body.reason,
            "guest_id": str(entry.guest_id) if entry.guest_id else None,
        },
        db=db,
    )
    return HunterQueueActionResponse(
        ok=True,
        id=str(entry.id),
        status=entry.status,
        reviewed_by=body.reviewed_by,
    )


@router.post(
    "/vrs/hunter/queue/{entry_id}/retry",
    response_model=HunterQueueActionResponse,
)
async def retry_hunter_queue_entry(
    entry_id: str,
    body: HunterRetryBody,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    entry = await _load_agent_queue_entry(db, entry_id)
    if entry.status != "failed":
        raise HTTPException(status_code=400, detail=f"Entry already {entry.status}")

    body_to_send = (entry.final_human_message or entry.original_ai_draft or "").strip()
    if not body_to_send:
        raise HTTPException(status_code=400, detail="Hunter queue entry has no message body to retry")

    entry.status = "sending"
    sent, error = await _deliver_hunter_message(db, entry, body_to_send, body.channel)
    entry.status = "delivered" if sent else "failed"
    entry.error_log = error
    await db.commit()
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="hunter.queue.retry",
        resource_type="hunter_queue",
        resource_id=str(entry.id),
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_retry",
        model_route="tool",
        outcome="success" if sent else "failed",
        metadata_json={
            "delivery_channel": body.channel,
            "delivery_status": "sent" if sent else "failed",
            "guest_id": str(getattr(entry, "guest_id", None)) if getattr(entry, "guest_id", None) else None,
        },
        db=db,
    )
    return HunterQueueActionResponse(
        ok=True,
        id=str(entry.id),
        status=entry.status,
        reviewed_by=body.reviewed_by,
        delivery_status="sent" if sent else "failed",
        delivery_channel=body.channel,
    )


@router.post("/vrs/hunter/audit", status_code=status.HTTP_202_ACCEPTED)
async def audit_hunter_console_event(
    payload: HunterAuditRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action=payload.event_name,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        purpose="reactivation_hunter",
        tool_name="vrs_hunter_glass",
        model_route="tool",
        outcome=payload.outcome,
        metadata_json=payload.metadata_json,
        db=db,
    )
    return {"status": "accepted"}

