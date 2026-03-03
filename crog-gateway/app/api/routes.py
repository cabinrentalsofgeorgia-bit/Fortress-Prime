"""
FastAPI Route Handlers

Webhooks and API endpoints for guest communication.
"""

import uuid
from datetime import datetime
from typing import Dict
from fastapi import APIRouter, Request, HTTPException, Depends
import structlog

from app.services.router import TrafficRouter
from app.models.domain import Message, MessageResponse, StranglerRouteDecision
from app.core.config import settings

logger = structlog.get_logger()
router = APIRouter()


def get_traffic_router() -> TrafficRouter:
    """
    Dependency injection for TrafficRouter.
    
    In production, this should be a singleton initialized at startup.
    """
    # This is a placeholder - actual initialization happens in main.py
    # You would typically inject this via dependency injection
    from app.main import traffic_router

    return traffic_router


@router.post("/webhooks/sms/incoming", response_model=Dict)
async def receive_sms_webhook(
    request: Request,
    router: TrafficRouter = Depends(get_traffic_router),
):
    """
    Webhook endpoint for incoming guest SMS messages.
    
    This endpoint receives webhooks from Twilio, RueBaRue, or other SMS providers
    and routes them through the Strangler Pattern logic.
    """
    trace_id = str(uuid.uuid4())
    log = logger.bind(trace_id=trace_id, endpoint="sms_webhook")

    try:
        # Parse webhook payload (Twilio sends form-encoded data)
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            # Twilio format
            form_data = await request.form()
            raw_payload = dict(form_data)
            log.info("received_twilio_webhook", from_number=raw_payload.get("From"))
            
            # Create Message object directly from Twilio format
            from app.models.domain import Message, MessageStatus
            
            # Normalize phone numbers (Twilio format to E.164)
            from_phone = raw_payload.get("From", "").strip()
            to_phone = raw_payload.get("To", "").strip()
            if not from_phone.startswith("+"):
                from_phone = "+" + from_phone
            if not to_phone.startswith("+"):
                to_phone = "+" + to_phone
            
            message = Message(
                message_id=raw_payload.get("MessageSid", "unknown"),
                from_phone=from_phone,
                to_phone=to_phone,
                body=raw_payload.get("Body", ""),
                received_at=datetime.utcnow(),
                trace_id=trace_id
            )
        else:
            # JSON format (RueBaRue or other providers)
            raw_payload = await request.json()
            log.info("incoming_sms_webhook", from_phone=raw_payload.get("from"))
            # Parse into our domain model
            message = await router.legacy_sms.receive_message(raw_payload, trace_id)

        # For Twilio inbound messages, just log and acknowledge
        # (Don't auto-reply unless AI replies are enabled)
        log.info(
            "twilio_message_received",
            phone=message.from_phone,
            body=message.body[:100],
        )

        # Only route/reply if AI replies are enabled
        if settings.enable_ai_replies:
            response, decision = await router.route_guest_message(message)
            log.info(
                "ai_reply_sent",
                route=decision.route_to,
                message_id=response.message_id,
            )
            return {
                "status": "success",
                "message_id": response.message_id,
                "route": decision.route_to,
                "auto_reply": True,
                "trace_id": trace_id,
            }
        else:
            # Just acknowledge receipt
            return {
                "status": "received",
                "message_id": message.message_id,
                "auto_reply": False,
                "note": "Message logged. AI replies disabled.",
                "trace_id": trace_id,
            }

    except Exception as e:
        log.error("sms_webhook_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process SMS webhook")


@router.post("/webhooks/sms/status", response_model=Dict)
async def receive_sms_status_webhook(request: Request):
    """
    Webhook endpoint for SMS delivery status updates from provider.
    
    Providers like RueBaRue send status updates (delivered, failed, etc.)
    """
    trace_id = str(uuid.uuid4())
    log = logger.bind(trace_id=trace_id, endpoint="status_webhook")

    try:
        payload = await request.json()
        log.info(
            "sms_status_update",
            message_id=payload.get("id"),
            status=payload.get("status"),
        )

        # TODO: Update message status in database
        # await update_message_status(payload["id"], payload["status"])

        return {"status": "acknowledged", "trace_id": trace_id}

    except Exception as e:
        log.error("status_webhook_error", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to process status webhook"
        )


@router.post("/api/messages/send", response_model=MessageResponse)
async def send_message_api(
    phone_number: str,
    message_body: str,
    router: TrafficRouter = Depends(get_traffic_router),
):
    """
    Manual API endpoint to send SMS (for testing or admin use).
    
    Usage:
    POST /api/messages/send
    {
        "phone_number": "+15551234567",
        "message_body": "Your access code is ready!"
    }
    """
    trace_id = str(uuid.uuid4())
    log = logger.bind(trace_id=trace_id, endpoint="send_message")

    try:
        log.info("manual_message_send", to_phone=phone_number)

        response = await router.legacy_sms.send_message(
            phone_number=phone_number,
            message_body=message_body,
            trace_id=trace_id,
        )

        log.info("message_sent", message_id=response.message_id)
        return response

    except Exception as e:
        log.error("send_message_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to send message")


@router.get("/api/reservations/{phone_number}", response_model=Dict)
async def lookup_reservation(
    phone_number: str,
    router: TrafficRouter = Depends(get_traffic_router),
):
    """
    Lookup guest reservation by phone number.
    
    Usage:
    GET /api/reservations/+15551234567
    """
    trace_id = str(uuid.uuid4())
    log = logger.bind(trace_id=trace_id, endpoint="lookup_reservation")

    try:
        log.info("reservation_lookup", phone=phone_number)

        reservation = await router.legacy_pms.get_reservation_by_phone(
            phone_number, trace_id
        )

        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")

        log.info("reservation_found", reservation_id=reservation.reservation_id)

        return {
            "reservation": reservation.model_dump(),
            "trace_id": trace_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error("reservation_lookup_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to lookup reservation")


@router.get("/health")
async def health_check():
    """
    Health check endpoint for load balancers.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/config")
async def get_config():
    """
    Configuration endpoint (feature flags status).
    
    DO NOT expose sensitive values in production!
    """
    return {
        "environment": settings.environment,
        "feature_flags": {
            "enable_ai_replies": settings.enable_ai_replies,
            "shadow_mode": settings.shadow_mode,
            "ai_intent_filter": settings.ai_intent_filter,
        },
        "note": "Sensitive configuration values are redacted",
    }
