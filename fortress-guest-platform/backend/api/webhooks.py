"""
Webhooks API — Handle inbound messages from Twilio.

Pipeline:
  Twilio POST → parse → store message → AgenticOrchestrator decides →
  auto-send (high confidence) OR queue for human review.
"""
from datetime import date
import re
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from twilio.request_validator import RequestValidator

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.websocket import emit_new_message, emit_review_queue_item
from backend.services.message_service import MessageService
from backend.services.agentic_orchestrator import AgenticOrchestrator
from backend.integrations.twilio_client import TwilioClient
from backend.models import (
    Guest,
    Reservation,
    AgentResponseQueue,
    ConciergeQueue,
    PropertyKnowledge,
)

router = APIRouter()
logger = structlog.get_logger()


def _sanitize_inbound_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]


def _normalize_e164_phone(value: str) -> str:
    phone = (value or "").strip()
    phone = re.sub(r"[^\d+]", "", phone)
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    return phone[:40]


def _infer_categories(body: str) -> list[str]:
    text = (body or "").lower()
    categories: list[str] = []
    if any(k in text for k in ("wifi", "wi-fi", "internet", "password")):
        categories.append("wifi")
    if any(k in text for k in ("hot tub", "hottub", "spa", "jacuzzi")):
        categories.append("hot_tub")
    if any(k in text for k in ("heat", "thermostat", "hvac", "a/c", "ac")):
        categories.append("hvac")
    if any(k in text for k in ("check in", "check-in", "arrival", "door code", "gate code")):
        categories.append("check_in")
    if any(k in text for k in ("check out", "check-out", "checkout", "departure")):
        categories.append("check_out")
    return categories


def _validate_twilio_signature(request: Request, form_data: dict[str, str]) -> bool:
    token = (settings.twilio_auth_token or "").strip()
    if not token:
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    validator = RequestValidator(token)
    return validator.validate(str(request.url), form_data, signature)


async def _retrieve_knowledge_context(
    db: AsyncSession,
    property_id,
    body: str,
    categories: list[str],
) -> list[dict]:
    records = []
    if property_id:
        if categories:
            by_category_stmt = (
                select(PropertyKnowledge)
                .where(
                    PropertyKnowledge.property_id == property_id,
                    PropertyKnowledge.category.in_(categories),
                )
                .order_by(PropertyKnowledge.updated_at.desc())
                .limit(5)
            )
            records = (await db.execute(by_category_stmt)).scalars().all()
        if not records:
            tokens = re.findall(r"[a-zA-Z]{4,}", (body or "").lower())[:6]
            if tokens:
                token_filters = [
                    PropertyKnowledge.content.ilike(f"%{token}%")
                    for token in tokens
                ]
                fallback_stmt = (
                    select(PropertyKnowledge)
                    .where(
                        PropertyKnowledge.property_id == property_id,
                        or_(*token_filters),
                    )
                    .order_by(PropertyKnowledge.updated_at.desc())
                    .limit(5)
                )
                records = (await db.execute(fallback_stmt)).scalars().all()
    elif categories:
        global_stmt = (
            select(PropertyKnowledge)
            .where(PropertyKnowledge.category.in_(categories))
            .order_by(PropertyKnowledge.updated_at.desc())
            .limit(5)
        )
        records = (await db.execute(global_stmt)).scalars().all()

    return [
        {
            "knowledge_id": str(item.id),
            "property_id": str(item.property_id),
            "category": item.category,
            "content": item.content[:1200],
        }
        for item in records
    ]


def _compose_concierge_draft(body: str, snippets: list[dict]) -> str:
    if snippets:
        return (
            "Thanks for your message. Here are the property instructions: "
            f"{snippets[0]['content']} "
            "If you need anything else, reply here and we will help right away."
        )[:1500]
    return (
        f"Thanks for reaching out about \"{body[:160]}\". "
        "I am pulling the exact property instructions now and will send a verified answer shortly."
    )


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

        # ── 3.5 VRS Message Router — Swarm-powered intent enrichment ──
        swarm_classification = {}
        try:
            from backend.services.vrs_message_router import classify_inbound_message
            prop_name = None
            if reservation and reservation.property_id:
                from backend.models.property import Property as _Prop
                _p = await db.get(_Prop, reservation.property_id)
                prop_name = _p.name if _p else None
            swarm_classification = await classify_inbound_message(
                db=db,
                guest_name=f"{guest.first_name or ''} {guest.last_name or ''}".strip() if guest else None,
                property_name=prop_name,
                text_body=body,
            )
            if swarm_classification.get("intent") and not message.intent:
                message.intent = swarm_classification["intent"]
        except Exception as router_exc:
            log.warning("vrs_message_router_failed", error=str(router_exc)[:200])

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

        try:
            await emit_new_message({
                "id": str(message.id),
                "direction": "inbound",
                "phone_from": from_phone,
                "body": (body or "")[:200],
                "intent": message.intent,
                "sentiment": message.sentiment,
                "requires_human_review": bool(message.requires_human_review),
                "guest_name": f"{guest.first_name or ''} {guest.last_name or ''}".strip() if guest else None,
                "created_at": str(message.created_at) if message.created_at else None,
                "swarm_intent": swarm_classification.get("intent"),
                "swarm_urgency": swarm_classification.get("urgency"),
                "swarm_suggested_reply": swarm_classification.get("suggested_reply"),
                "swarm_ai_source": swarm_classification.get("ai_source"),
            })
        except Exception:
            pass

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


@router.post("/sms/incoming/concierge")
async def handle_incoming_sms_concierge(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Twilio inbound webhook for concierge queueing.
    Validates request signature, sanitizes payload, retrieves property knowledge,
    and stores a pending human-review draft in concierge_queue.
    """
    log = logger.bind(endpoint="incoming_sms_concierge")

    try:
        form_data = await request.form()
        raw = {k: str(v) for k, v in form_data.items()}

        if not _validate_twilio_signature(request, raw):
            log.warning("twilio_signature_invalid")
            return Response(status_code=403)

        twilio_client = TwilioClient()
        parsed = twilio_client.parse_webhook(raw)
        inbound_phone = _normalize_e164_phone(parsed.get("from") or "")
        inbound_body = _sanitize_inbound_text(parsed.get("body") or "")
        message_sid = (parsed.get("message_sid") or "").strip()

        if not inbound_phone or not inbound_body:
            log.warning("concierge_payload_invalid", has_phone=bool(inbound_phone), has_body=bool(inbound_body))
            return Response(status_code=400)

        service = MessageService(db, twilio_client)
        message = await service.receive_sms(
            external_id=message_sid,
            from_phone=inbound_phone,
            body=inbound_body,
            metadata=parsed,
        )

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

        property_id = reservation.property_id if reservation else None
        categories = _infer_categories(inbound_body)
        snippets = await _retrieve_knowledge_context(
            db=db,
            property_id=property_id,
            body=inbound_body,
            categories=categories,
        )
        queue_item = ConciergeQueue(
            guest_phone=inbound_phone,
            property_id=property_id,
            inbound_message=inbound_body,
            retrieved_context={
                "message_sid": message_sid,
                "guest_id": str(guest.id) if guest else None,
                "reservation_id": str(reservation.id) if reservation else None,
                "inferred_categories": categories,
                "knowledge_snippets": snippets,
            },
            # Daemon-owned drafting: enqueue blank and let concierge_worker infer.
            ai_draft_reply="",
            status="pending_review",
        )
        db.add(queue_item)
        await db.commit()
        log.info(
            "concierge_queue_item_created",
            queue_id=str(queue_item.id),
            property_id=str(property_id) if property_id else None,
            snippets=len(snippets),
        )
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
            status_code=200,
        )
    except Exception as e:
        await db.rollback()
        log.error("concierge_webhook_failed", error=str(e), exc_info=True)
        # Return 200 to prevent Twilio retry storms while preserving server logs.
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
