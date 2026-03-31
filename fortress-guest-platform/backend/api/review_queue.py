"""
Review Queue API — Human-in-the-loop for AI-generated guest responses.

Endpoints:
  GET  /queue              — list pending responses
  GET  /queue/stats        — queue depth + performance metrics
  GET  /queue/{id}         — single entry with full context
  POST /queue/{id}/approve — send proposed response as-is
  POST /queue/{id}/edit    — edit text then send
  POST /queue/{id}/reject  — discard the proposed response
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models import AgentResponseQueue, Message, Guest
from backend.services.message_service import MessageService
from backend.integrations.twilio_client import TwilioClient

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])
logger = structlog.get_logger()


# ── Pydantic request / response schemas ──

class EditBody(BaseModel):
    final_response: str
    reviewed_by: str = "admin"


class ApproveBody(BaseModel):
    reviewed_by: str = "admin"


class RejectBody(BaseModel):
    reviewed_by: str = "admin"
    reason: Optional[str] = None


# ── Endpoints ──

@router.get("/queue")
async def list_queue(
    status: str = Query("pending", description="pending|approved|rejected|sent|all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List review queue entries with inbound message context."""
    query = (
        select(AgentResponseQueue)
        .options(
            selectinload(AgentResponseQueue.inbound_message),
            selectinload(AgentResponseQueue.guest),
            selectinload(AgentResponseQueue.reservation),
        )
        .order_by(desc(AgentResponseQueue.created_at))
    )

    if status != "all":
        query = query.where(AgentResponseQueue.status == status)

    count_q = select(func.count(AgentResponseQueue.id))
    if status != "all":
        count_q = count_q.where(AgentResponseQueue.status == status)
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset(offset).limit(limit)
    rows = (await db.execute(query)).scalars().all()

    items = []
    for q in rows:
        msg = q.inbound_message
        guest = q.guest
        items.append({
            "id": str(q.id),
            "status": q.status,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            # Inbound message context
            "from_phone": msg.phone_from if msg else None,
            "inbound_body": msg.body if msg else None,
            "inbound_time": msg.created_at.isoformat() if msg and msg.created_at else None,
            # Guest
            "guest_name": guest.full_name if guest else None,
            "guest_phone": guest.phone_number if guest else None,
            # Classification
            "intent": q.intent,
            "sentiment": q.sentiment_label,
            "urgency": q.urgency_level,
            "confidence": round(q.confidence, 3) if q.confidence else 0,
            "action": q.action,
            "escalation_reason": q.escalation_reason,
            # Proposed response
            "proposed_response": q.proposed_response,
            "final_response": q.final_response,
            # Review
            "reviewed_by": q.reviewed_by,
            "reviewed_at": q.reviewed_at.isoformat() if q.reviewed_at else None,
        })

    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/queue/stats")
async def queue_stats(db: AsyncSession = Depends(get_db)):
    """Queue depth and review performance metrics."""
    pending = (await db.execute(
        select(func.count(AgentResponseQueue.id))
        .where(AgentResponseQueue.status == "pending")
    )).scalar() or 0

    approved = (await db.execute(
        select(func.count(AgentResponseQueue.id))
        .where(AgentResponseQueue.status.in_(["approved", "sent"]))
    )).scalar() or 0

    rejected = (await db.execute(
        select(func.count(AgentResponseQueue.id))
        .where(AgentResponseQueue.status == "rejected")
    )).scalar() or 0

    edited = (await db.execute(
        select(func.count(AgentResponseQueue.id))
        .where(AgentResponseQueue.status == "edited")
    )).scalar() or 0

    avg_conf = (await db.execute(
        select(func.avg(AgentResponseQueue.confidence))
        .where(AgentResponseQueue.status == "pending")
    )).scalar()

    return {
        "pending": pending,
        "approved": approved,
        "edited": edited,
        "rejected": rejected,
        "total_reviewed": approved + edited + rejected,
        "avg_pending_confidence": round(float(avg_conf), 3) if avg_conf else 0,
    }


@router.get("/queue/{entry_id}")
async def get_queue_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single queue entry with full conversation thread."""
    entry = await db.get(AgentResponseQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")

    msg = await db.get(Message, entry.message_id) if entry.message_id else None
    guest = await db.get(Guest, entry.guest_id) if entry.guest_id else None

    # Pull recent conversation thread for context
    thread = []
    if guest:
        thread_q = await db.execute(
            select(Message)
            .where(Message.guest_id == guest.id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        for m in reversed(list(thread_q.scalars().all())):
            thread.append({
                "direction": m.direction,
                "body": m.body,
                "time": m.created_at.isoformat() if m.created_at else None,
                "is_auto": m.is_auto_response,
            })

    return {
        "entry": {
            "id": str(entry.id),
            "status": entry.status,
            "intent": entry.intent,
            "sentiment": entry.sentiment_label,
            "urgency": entry.urgency_level,
            "confidence": round(entry.confidence, 3) if entry.confidence else 0,
            "action": entry.action,
            "escalation_reason": entry.escalation_reason,
            "proposed_response": entry.proposed_response,
            "final_response": entry.final_response,
            "decision_metadata": entry.decision_metadata,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        },
        "inbound_message": {
            "body": msg.body if msg else None,
            "from_phone": msg.phone_from if msg else None,
            "time": msg.created_at.isoformat() if msg and msg.created_at else None,
        },
        "guest": {
            "name": guest.full_name if guest else None,
            "phone": guest.phone_number if guest else None,
            "total_stays": guest.total_stays if guest else 0,
        } if guest else None,
        "conversation_thread": thread,
    }


@router.post("/queue/{entry_id}/approve")
async def approve_and_send(
    entry_id: UUID,
    body: ApproveBody,
    db: AsyncSession = Depends(get_db),
):
    """Approve the proposed response and send it to the guest."""
    entry = await db.get(AgentResponseQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    if entry.status != "pending":
        raise HTTPException(400, f"Entry already {entry.status}")

    response_text = entry.proposed_response
    sent_msg = await _send_response(db, entry, response_text)

    entry.status = "approved"
    entry.final_response = response_text
    entry.reviewed_by = body.reviewed_by
    entry.reviewed_at = datetime.utcnow()
    entry.sent_message_id = sent_msg.id
    await db.commit()

    return {"ok": True, "status": "approved", "sent_message_id": str(sent_msg.id)}


@router.post("/queue/{entry_id}/edit")
async def edit_and_send(
    entry_id: UUID,
    body: EditBody,
    db: AsyncSession = Depends(get_db),
):
    """Edit the response text and send the revised version."""
    entry = await db.get(AgentResponseQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    if entry.status != "pending":
        raise HTTPException(400, f"Entry already {entry.status}")

    if not body.final_response.strip():
        raise HTTPException(400, "Response text cannot be empty")

    sent_msg = await _send_response(db, entry, body.final_response)

    entry.status = "edited"
    entry.final_response = body.final_response
    entry.reviewed_by = body.reviewed_by
    entry.reviewed_at = datetime.utcnow()
    entry.sent_message_id = sent_msg.id
    await db.commit()

    return {"ok": True, "status": "edited", "sent_message_id": str(sent_msg.id)}


@router.post("/queue/{entry_id}/reject")
async def reject_response(
    entry_id: UUID,
    body: RejectBody,
    db: AsyncSession = Depends(get_db),
):
    """Reject the proposed response without sending anything."""
    entry = await db.get(AgentResponseQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    if entry.status != "pending":
        raise HTTPException(400, f"Entry already {entry.status}")

    entry.status = "rejected"
    entry.reviewed_by = body.reviewed_by
    entry.reviewed_at = datetime.utcnow()
    if body.reason:
        meta = entry.decision_metadata or {}
        meta["rejection_reason"] = body.reason
        entry.decision_metadata = meta
    await db.commit()

    return {"ok": True, "status": "rejected"}


# ── Internal helper ──

async def _send_response(
    db: AsyncSession,
    entry: AgentResponseQueue,
    text: str,
) -> Message:
    """Send a response via Twilio and persist the outbound Message."""
    inbound = await db.get(Message, entry.message_id) if entry.message_id else None
    if not inbound:
        raise HTTPException(400, "Original inbound message not found")

    to_phone = inbound.phone_from
    twilio = TwilioClient()
    service = MessageService(db, twilio)

    sent_msg = await service.send_sms(
        to_phone=to_phone,
        body=text,
        guest_id=entry.guest_id,
        reservation_id=entry.reservation_id,
        is_auto_response=False,
        ai_confidence=entry.confidence,
    )

    # Mark the inbound message as reviewed
    inbound.requires_human_review = False
    inbound.human_reviewed_at = datetime.utcnow()
    inbound.human_reviewed_by = entry.reviewed_by or "admin"

    return sent_msg
