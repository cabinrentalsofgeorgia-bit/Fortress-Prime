"""
Copilot Queue API — Human-in-the-loop draft management.

Endpoints:
  GET    /api/copilot-queue/pending       — Drafted messages awaiting approval
  PUT    /api/copilot-queue/{id}          — Edit rendered subject/body
  POST   /api/copilot-queue/{id}/approve  — Approve, dispatch via SMTP, mark sent
  POST   /api/copilot-queue/{id}/cancel   — Cancel a drafted message
"""
import asyncio
from typing import List, Optional
from uuid import UUID

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models.message_queue import MessageQueue
from backend.models.quote import Quote, QuoteOption
from backend.services.async_jobs import enqueue_async_job, extract_request_actor
from backend.services.email_service import is_email_configured, send_email

logger = structlog.get_logger(service="copilot_queue")
router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


# ── Schemas ──────────────────────────────────────────────────────────────────


class DraftResponse(BaseModel):
    id: UUID
    quote_id: UUID
    template_id: UUID
    status: str
    rendered_subject: str
    rendered_body: str
    created_at: Optional[str] = None
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    property_name: Optional[str] = None
    template_name: Optional[str] = None
    dispatch_job_id: Optional[str] = None


class EditDraftRequest(BaseModel):
    rendered_subject: Optional[str] = Field(None, max_length=1000)
    rendered_body: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _draft_to_response(msg: MessageQueue) -> DraftResponse:
    guest_name = None
    guest_email = None
    property_name = None

    if msg.quote and msg.quote.lead:
        guest_name = msg.quote.lead.guest_name
        guest_email = msg.quote.lead.email
    if msg.quote and msg.quote.options:
        first_opt = msg.quote.options[0] if msg.quote.options else None
        if first_opt and first_opt.property:
            property_name = first_opt.property.name

    return DraftResponse(
        id=msg.id,
        quote_id=msg.quote_id,
        template_id=msg.template_id,
        status=msg.status,
        rendered_subject=msg.rendered_subject,
        rendered_body=msg.rendered_body,
        created_at=msg.created_at.isoformat() if msg.created_at else None,
        guest_name=guest_name,
        guest_email=guest_email,
        property_name=property_name,
        template_name=msg.template.name if msg.template else None,
    )


async def _dispatch_email(msg_id: UUID) -> None:
    """Background task: send the email for an approved message and update status."""
    from backend.core.database import AsyncSessionLocal
    normalized_msg_id = UUID(str(msg_id))

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MessageQueue)
            .options(
                joinedload(MessageQueue.quote).joinedload(Quote.lead),
            )
            .where(MessageQueue.id == normalized_msg_id)
        )
        msg = result.unique().scalar_one_or_none()
        if not msg:
            logger.error("dispatch_msg_not_found", msg_id=str(normalized_msg_id))
            return

        to_email = msg.quote.lead.email if msg.quote and msg.quote.lead else None
        if not to_email:
            logger.error("dispatch_no_recipient", msg_id=str(msg_id))
            msg.status = "cancelled"
            await db.commit()
            return

        if not is_email_configured():
            logger.warning(
                "dispatch_smtp_not_configured",
                msg_id=str(normalized_msg_id),
                to=to_email,
            )
            msg.status = "sent"
            await db.commit()
            return

        try:
            sent = await asyncio.to_thread(
                send_email,
                to_email,
                msg.rendered_subject,
                msg.rendered_body,
                "",
                None,
            )
            msg.status = "sent" if sent else "approved"
            logger.info(
                "copilot_dispatch_complete",
                msg_id=str(normalized_msg_id),
                to=to_email,
                success=sent,
            )
        except Exception as exc:
            logger.error(
                "copilot_dispatch_error",
                msg_id=str(normalized_msg_id),
                error=str(exc),
            )

        await db.commit()


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/pending", response_model=List[DraftResponse])
async def list_pending_drafts(db: AsyncSession = Depends(get_db)):
    """Return all messages with status 'drafted', eager-loading quote/lead/template."""
    result = await db.execute(
        select(MessageQueue)
        .options(
            joinedload(MessageQueue.quote)
            .joinedload(Quote.lead),
            joinedload(MessageQueue.quote)
            .selectinload(Quote.options)
            .joinedload(QuoteOption.property),
            joinedload(MessageQueue.template),
        )
        .where(MessageQueue.status == "drafted")
        .order_by(MessageQueue.created_at.desc())
    )
    messages = result.unique().scalars().all()
    return [_draft_to_response(m) for m in messages]


@router.put("/{msg_id}", response_model=DraftResponse)
async def edit_draft(
    msg_id: UUID,
    body: EditDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """Edit the rendered subject/body of a drafted message."""
    result = await db.execute(
        select(MessageQueue)
        .options(
            joinedload(MessageQueue.quote).joinedload(Quote.lead),
            joinedload(MessageQueue.quote)
            .selectinload(Quote.options)
            .joinedload(QuoteOption.property),
            joinedload(MessageQueue.template),
        )
        .where(MessageQueue.id == msg_id)
    )
    msg = result.unique().scalar_one_or_none()
    if not msg:
        raise HTTPException(404, f"Message {msg_id} not found")
    if msg.status != "drafted":
        raise HTTPException(409, f"Cannot edit message in '{msg.status}' state")

    if body.rendered_subject is not None:
        msg.rendered_subject = body.rendered_subject
    if body.rendered_body is not None:
        msg.rendered_body = body.rendered_body

    await db.commit()
    await db.refresh(msg)
    return _draft_to_response(msg)


@router.post("/{msg_id}/approve", response_model=DraftResponse)
async def approve_draft(
    msg_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    """Approve a drafted message: set status to approved and queue SMTP dispatch."""
    result = await db.execute(
        select(MessageQueue)
        .options(
            joinedload(MessageQueue.quote).joinedload(Quote.lead),
            joinedload(MessageQueue.quote)
            .selectinload(Quote.options)
            .joinedload(QuoteOption.property),
            joinedload(MessageQueue.template),
        )
        .where(MessageQueue.id == msg_id)
        .with_for_update()
    )
    msg = result.unique().scalar_one_or_none()
    if not msg:
        raise HTTPException(404, f"Message {msg_id} not found")
    if msg.status != "drafted":
        raise HTTPException(409, f"Cannot approve message in '{msg.status}' state")

    msg.status = "approved"
    await db.commit()
    await db.refresh(msg)

    dispatch_job = await enqueue_async_job(
        db,
        worker_name="dispatch_copilot_email_job",
        job_name="dispatch_copilot_email",
        payload={"message_id": str(msg.id)},
        requested_by=extract_request_actor(
            request.headers.get("x-user-id"),
            request.headers.get("x-user-email"),
        ),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )

    logger.info(
        "copilot_draft_approved",
        msg_id=str(msg_id),
        guest=msg.quote.lead.guest_name if msg.quote and msg.quote.lead else None,
    )

    response = _draft_to_response(msg)
    response.dispatch_job_id = str(dispatch_job.id)
    return response


@router.post("/{msg_id}/cancel", response_model=DraftResponse)
async def cancel_draft(
    msg_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a drafted message."""
    result = await db.execute(
        select(MessageQueue)
        .options(
            joinedload(MessageQueue.quote).joinedload(Quote.lead),
            joinedload(MessageQueue.quote)
            .selectinload(Quote.options)
            .joinedload(QuoteOption.property),
            joinedload(MessageQueue.template),
        )
        .where(MessageQueue.id == msg_id)
    )
    msg = result.unique().scalar_one_or_none()
    if not msg:
        raise HTTPException(404, f"Message {msg_id} not found")
    if msg.status not in ("drafted", "approved"):
        raise HTTPException(409, f"Cannot cancel message in '{msg.status}' state")

    msg.status = "cancelled"
    await db.commit()
    await db.refresh(msg)

    logger.info("copilot_draft_cancelled", msg_id=str(msg_id))

    return _draft_to_response(msg)
