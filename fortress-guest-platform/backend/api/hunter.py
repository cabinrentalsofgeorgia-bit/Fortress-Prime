from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS, PULSE_ACCESS
from backend.core.database import get_db
from backend.models.hunter import HunterQueueEntry
from backend.models.hunter_recovery_op import HunterRecoveryOp, HunterRecoveryOpStatus
from backend.models.storefront_session_guest_link import StorefrontSessionGuestLink
from backend.models.guest import Guest
from backend.models.staff import StaffUser
from backend.integrations.twilio_client import TwilioClient
from backend.services.communication_service import CommunicationService
from backend.services.async_jobs import enqueue_async_job
from backend.services.hunter_service import delete_hunter_candidate
from backend.services.openshell_audit import record_audit_event

router = APIRouter()

_STATUS_FILTER_ALIASES: dict[str, tuple[str, ...]] = {
    "pending_review": ("queued", "processing"),
    "active": ("queued", "processing"),
    "queued": ("queued",),
    "processing": ("processing",),
    "sent": ("sent",),
    "failed": ("failed",),
    "cancelled": ("cancelled",),
}


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

