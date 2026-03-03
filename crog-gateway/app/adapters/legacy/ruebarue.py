"""
RueBaRue SMS Provider Adapter

Implements the SMSService interface for RueBaRue's API.
Uses tenacity for automatic retries on network failures.
"""

import uuid
from datetime import datetime
from typing import Optional
import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.interfaces import SMSService
from app.models.domain import (
    Message,
    MessageResponse,
    MessageStatus,
    MessageIntent,
)

logger = structlog.get_logger()


class RueBaRueAdapter(SMSService):
    """
    RueBaRue SMS Provider Implementation
    
    This adapter translates our domain models to/from RueBaRue's API format.
    """

    def __init__(self):
        self.api_url = settings.ruebarue_api_url
        self.username = getattr(settings, 'ruebarue_username', '')
        self.password = getattr(settings, 'ruebarue_password', '')
        self.api_key = getattr(settings, 'ruebarue_api_key', '')
        self.phone_number = settings.ruebarue_phone_number
        self.log = logger.bind(adapter="ruebarue")

        # Use username/password auth if available, otherwise API key
        headers = {"Content-Type": "application/json"}
        if self.username and self.password:
            # RueBaRue uses basic auth
            import base64
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=settings.http_timeout_seconds,
            headers=headers,
        )

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=settings.retry_wait_seconds,
            max=60,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def send_message(
        self,
        phone_number: str,
        message_body: str,
        trace_id: str,
    ) -> MessageResponse:
        """
        Send SMS via RueBaRue API with automatic retry.
        
        API Endpoint: POST /messages
        """
        log = self.log.bind(trace_id=trace_id, to_phone=phone_number)
        log.info("sending_sms_via_ruebarue", body_length=len(message_body))

        payload = {
            "from": self.phone_number,
            "to": phone_number,
            "body": message_body,
            "callback_url": f"{settings.app_name}/webhooks/ruebarue/status",
        }

        try:
            response = await self.client.post("/messages", json=payload)
            response.raise_for_status()

            data = response.json()
            log.info("sms_sent_successfully", message_id=data.get("id"))

            return MessageResponse(
                message_id=data.get("id", str(uuid.uuid4())),
                status=self._map_status(data.get("status", "sent")),
                body=message_body,
                sent_at=datetime.now(),
                trace_id=trace_id,
                provider="ruebarue",
                metadata={"raw_response": data},
            )

        except httpx.HTTPStatusError as e:
            log.error(
                "ruebarue_api_error",
                status_code=e.response.status_code,
                error=str(e),
            )
            # Return failed response instead of raising
            return MessageResponse(
                message_id=str(uuid.uuid4()),
                status=MessageStatus.FAILED,
                body=message_body,
                sent_at=datetime.now(),
                trace_id=trace_id,
                provider="ruebarue",
                metadata={"error": str(e)},
            )

    async def receive_message(
        self,
        raw_payload: dict,
        trace_id: str,
    ) -> Message:
        """
        Parse incoming RueBaRue webhook payload.
        
        Expected webhook format:
        {
            "id": "msg_123",
            "from": "+15551234567",
            "to": "+15559876543",
            "body": "Guest message text",
            "received_at": "2024-01-15T10:30:00Z"
        }
        """
        log = self.log.bind(trace_id=trace_id)
        log.info("parsing_ruebarue_webhook", message_id=raw_payload.get("id"))

        return Message(
            message_id=raw_payload.get("id", str(uuid.uuid4())),
            from_phone=raw_payload["from"],
            to_phone=raw_payload["to"],
            body=raw_payload["body"],
            received_at=datetime.fromisoformat(
                raw_payload.get("received_at", datetime.now().isoformat())
            ),
            trace_id=trace_id,
            raw_payload=raw_payload,
        )

    async def classify_intent(
        self,
        message: Message,
        trace_id: str,
    ) -> MessageIntent:
        """
        Classify message intent using simple keyword matching.
        
        Production version would use AI/NLP for better accuracy.
        """
        log = self.log.bind(trace_id=trace_id, message_id=message.message_id)

        body_lower = message.body.lower()

        # Simple keyword matching (placeholder logic)
        if any(word in body_lower for word in ["wifi", "wi-fi", "internet", "password"]):
            intent = MessageIntent.WIFI_QUESTION
        elif any(
            word in body_lower for word in ["code", "lock", "door", "access", "key"]
        ):
            intent = MessageIntent.ACCESS_CODE_REQUEST
        elif any(
            word in body_lower for word in ["check in", "checkin", "arrive", "arrival"]
        ):
            intent = MessageIntent.CHECKIN_QUESTION
        elif any(
            word in body_lower
            for word in ["check out", "checkout", "leave", "departure"]
        ):
            intent = MessageIntent.CHECKOUT_QUESTION
        elif any(
            word in body_lower
            for word in ["broken", "fix", "repair", "maintenance", "not working"]
        ):
            intent = MessageIntent.MAINTENANCE_REQUEST
        elif any(
            word in body_lower
            for word in ["pool", "hot tub", "grill", "fireplace", "amenity"]
        ):
            intent = MessageIntent.AMENITY_QUESTION
        else:
            intent = MessageIntent.UNKNOWN

        log.info("intent_classified", intent=intent.value, body_preview=body_lower[:50])
        return intent

    def _map_status(self, ruebarue_status: str) -> MessageStatus:
        """Map RueBaRue status codes to our domain enum"""
        status_map = {
            "queued": MessageStatus.QUEUED,
            "sent": MessageStatus.SENT,
            "delivered": MessageStatus.DELIVERED,
            "failed": MessageStatus.FAILED,
            "undeliverable": MessageStatus.UNDELIVERABLE,
        }
        return status_map.get(ruebarue_status.lower(), MessageStatus.SENT)

    async def close(self):
        """Cleanup HTTP client"""
        await self.client.aclose()
