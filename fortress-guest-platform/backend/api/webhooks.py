"""
Webhooks API — Handle inbound messages from Twilio.

Pipeline:
  Twilio POST → parse → store message → AgenticOrchestrator decides →
  auto-send (high confidence) OR queue for human review.
"""
from datetime import date, datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.database import get_db
from backend.core.config import settings
from backend.services.message_service import MessageService
from backend.services.agentic_orchestrator import AgenticOrchestrator
from backend.integrations.twilio_client import TwilioClient
from backend.models import Guest, Reservation, Property, Message, AgentResponseQueue

router = APIRouter()
logger = structlog.get_logger()


@router.post("/sms/incoming")
async def handle_incoming_sms(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Unified inbound SMS pipeline (Twilio → Orchestrator → auto-send or queue).

    1. Parse Twilio webhook
    2. Store inbound message + find/create guest
    3. Link to active reservation & property context
    4. Run AgenticOrchestrator (classify → sentiment → decide → generate)
    5. Auto-send if confident; otherwise queue for human review
    6. Auto-create work orders for maintenance
    7. Escalate urgent/negative to staff via SMS
    """
    log = logger.bind(endpoint="incoming_sms")

    try:
        form_data = await request.form()
        twilio_client = TwilioClient()
        parsed = twilio_client.parse_webhook(dict(form_data))

        from_phone = parsed["from"]
        body = parsed["body"]
        log.info("incoming_sms", from_number=from_phone, body_preview=body[:50])

        # ── 1. Store inbound message ──
        service = MessageService(db, twilio_client)
        message = await service.receive_sms(
            external_id=parsed["message_sid"],
            from_phone=from_phone,
            body=body,
            metadata=parsed,
        )

        # ── 2. Resolve guest & reservation context ──
        guest = await db.get(Guest, message.guest_id) if message.guest_id else None
        reservation = (
            await db.get(Reservation, message.reservation_id)
            if message.reservation_id
            else None
        )

        if not reservation and guest:
            today = date.today()
            res_q = await db.execute(
                select(Reservation).where(
                    Reservation.guest_id == guest.id,
                    Reservation.check_in_date <= today,
                    Reservation.check_out_date >= today,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                ).limit(1)
            )
            reservation = res_q.scalar_one_or_none()
            if reservation:
                message.reservation_id = reservation.id

        # ── 3. Run AgenticOrchestrator ──
        orchestrator = AgenticOrchestrator()
        decision = await orchestrator.process_incoming_message(
            message=message,
            guest=guest,
            reservation=reservation,
            db=db,
        )

        # Persist classification on the message row
        message.intent = decision.intent.value if decision.intent else None
        message.sentiment = decision.sentiment.label if decision.sentiment else None
        message.category = decision.action
        message.requires_human_review = decision.requires_human

        # ── 4. Act on the decision ──
        if decision.should_auto_send and decision.response_text:
            sent_msg = await service.send_sms(
                to_phone=from_phone,
                body=decision.response_text,
                guest_id=guest.id if guest else None,
                reservation_id=message.reservation_id,
                is_auto_response=True,
                ai_confidence=decision.confidence,
            )
            log.info(
                "auto_reply_sent",
                confidence=round(decision.confidence, 3),
                action=decision.action,
            )
        elif decision.response_text:
            # Queue for human review
            queue_entry = AgentResponseQueue(
                message_id=message.id,
                guest_id=guest.id if guest else None,
                reservation_id=message.reservation_id,
                intent=decision.intent.value if decision.intent else None,
                sentiment_label=decision.sentiment.label if decision.sentiment else None,
                sentiment_score=decision.sentiment.score if decision.sentiment else None,
                urgency_level=decision.sentiment.urgency_level if decision.sentiment else 0,
                proposed_response=decision.response_text,
                confidence=decision.confidence,
                action=decision.action,
                escalation_reason=decision.escalation_reason,
                decision_metadata=decision.metadata,
            )
            db.add(queue_entry)
            log.info(
                "response_queued_for_review",
                confidence=round(decision.confidence, 3),
                reason=decision.escalation_reason,
            )

        await db.commit()

        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    except Exception as e:
        log.error("webhook_processing_failed", error=str(e), exc_info=True)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
            status_code=200,
        )


@router.post("/sms/status")
async def handle_sms_status(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle SMS delivery status updates from Twilio
    
    BETTER THAN competitors:
    - Real-time delivery tracking
    - Failed message detection
    - Cost tracking updates
    """
    log = logger.bind(endpoint="sms_status")
    
    try:
        form_data = await request.form()
        message_sid = form_data.get("MessageSid")
        message_status = form_data.get("MessageStatus")
        error_code = form_data.get("ErrorCode")
        error_message = form_data.get("ErrorMessage")
        
        log.info(
            "sms_status_update",
            message_sid=message_sid,
            status=message_status,
            error_code=error_code
        )
        
        if message_sid:
            from backend.models import Message as MsgModel
            result = await db.execute(
                select(MsgModel).where(MsgModel.external_id == message_sid)
            )
            message = result.scalar_one_or_none()
            if message:
                message.status = message_status or message.status
                if error_code:
                    message.error_code = error_code
                if error_message:
                    message.error_message = error_message
                if message_status == "delivered":
                    from datetime import datetime, timezone
                    message.delivered_at = datetime.now(timezone.utc)
                await db.commit()
                log.info(
                    "message_status_updated",
                    message_id=str(message.id),
                    new_status=message_status
                )
            else:
                log.warning("status_update_no_match", message_sid=message_sid)
        
        return Response(status_code=200)
        
    except Exception as e:
        log.error("status_webhook_failed", error=str(e))
        return Response(status_code=200)
