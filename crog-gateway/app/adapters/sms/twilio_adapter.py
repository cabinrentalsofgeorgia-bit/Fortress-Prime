"""
Twilio SMS Adapter
Production-grade integration with Twilio SMS API
"""

import base64
from typing import Optional, Dict
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import structlog

from app.core.interfaces import SMSService
from app.core.config import settings
from app.models.domain import Message, MessageStatus

logger = structlog.get_logger()


class TwilioAdapter(SMSService):
    """
    Twilio SMS Provider Adapter
    
    Implements the SMSService interface for Twilio's API.
    Includes retry logic, error handling, and delivery tracking.
    """
    
    def __init__(self):
        self.account_sid = settings.twilio_account_sid
        self.auth_token = settings.twilio_auth_token
        self.from_phone = settings.twilio_phone_number
        self.api_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
        
        self.log = logger.bind(adapter="twilio")
        
        # Create auth header
        credentials = f"{self.account_sid}:{self.auth_token}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()
        
        self.client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=settings.http_timeout_seconds,
            headers={
                "Authorization": f"Basic {b64_credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        
        self.log.info("twilio_adapter_initialized", from_phone=self.from_phone)
    
    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=1,
            max=30
        ),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def send(self, to: str, body: str, trace_id: str) -> Message:
        """
        Send SMS via Twilio
        
        Args:
            to: Recipient phone number (E.164 format)
            body: Message text
            trace_id: Request trace ID for logging
            
        Returns:
            Message object with Twilio message SID and status
        """
        log = self.log.bind(trace_id=trace_id, to=to)
        log.info("sending_sms", body_length=len(body))
        
        try:
            # Twilio API expects form data
            form_data = {
                "To": to,
                "From": self.from_phone,
                "Body": body,
            }
            
            response = await self.client.post("/Messages.json", data=form_data)
            response.raise_for_status()
            
            data = response.json()
            
            message = Message(
                message_id=data["sid"],
                phone_number=to,
                body=body,
                direction="outbound",
                status=MessageStatus(data["status"]),
                provider="twilio",
                cost_usd=float(data.get("price", "0")),
                trace_id=trace_id
            )
            
            log.info(
                "sms_sent_success",
                message_id=message.message_id,
                status=message.status,
                cost=message.cost_usd
            )
            
            return message
            
        except httpx.HTTPStatusError as e:
            log.error(
                "twilio_api_error",
                status_code=e.response.status_code,
                error=e.response.text
            )
            raise
        except Exception as e:
            log.error("send_sms_exception", error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def receive(self, webhook_data: Dict, trace_id: str) -> Message:
        """
        Parse incoming Twilio webhook
        
        Twilio sends POST data with:
        - MessageSid: Unique message ID
        - From: Sender phone number
        - To: Your Twilio number
        - Body: Message text
        - NumMedia: Number of media items (for MMS)
        
        Args:
            webhook_data: Raw webhook POST data from Twilio
            trace_id: Request trace ID
            
        Returns:
            Message object parsed from webhook
        """
        log = self.log.bind(trace_id=trace_id)
        log.info("receiving_sms", from_number=webhook_data.get("From"))
        
        try:
            message = Message(
                message_id=webhook_data.get("MessageSid"),
                phone_number=webhook_data.get("From"),
                body=webhook_data.get("Body", ""),
                direction="inbound",
                status=MessageStatus.RECEIVED,
                provider="twilio",
                to_phone=webhook_data.get("To"),
                trace_id=trace_id
            )
            
            # Handle MMS
            num_media = int(webhook_data.get("NumMedia", 0))
            if num_media > 0:
                media_urls = []
                for i in range(num_media):
                    media_url = webhook_data.get(f"MediaUrl{i}")
                    if media_url:
                        media_urls.append(media_url)
                message.media_urls = media_urls
                log.info("mms_received", media_count=num_media)
            
            log.info(
                "sms_received_success",
                message_id=message.message_id,
                body_length=len(message.body)
            )
            
            return message
            
        except Exception as e:
            log.error("receive_sms_exception", error=str(e))
            raise
    
    async def get_message_status(self, message_id: str, trace_id: str) -> MessageStatus:
        """
        Get delivery status of a sent message
        
        Args:
            message_id: Twilio message SID
            trace_id: Request trace ID
            
        Returns:
            Current message status
        """
        log = self.log.bind(trace_id=trace_id, message_id=message_id)
        log.info("checking_message_status")
        
        try:
            response = await self.client.get(f"/Messages/{message_id}.json")
            response.raise_for_status()
            
            data = response.json()
            status = MessageStatus(data["status"])
            
            log.info("message_status_retrieved", status=status)
            
            return status
            
        except Exception as e:
            log.error("status_check_exception", error=str(e))
            raise
    
    async def classify_intent(self, message: Message, trace_id: str) -> str:
        """
        Classify message intent using simple keyword matching
        
        More sophisticated intent classification happens in AI layer.
        This is a fast, rule-based pre-filter.
        
        Args:
            message: Incoming message
            trace_id: Request trace ID
            
        Returns:
            Intent string (e.g., 'CHECKIN', 'WIFI', 'DIRECTIONS')
        """
        body_lower = message.body.lower()
        
        # Simple keyword-based classification
        intent_keywords = {
            "CHECKIN": ["check in", "checkin", "check-in", "arrival", "door code", "access code"],
            "CHECKOUT": ["check out", "checkout", "check-out", "departure", "leaving"],
            "WIFI": ["wifi", "wi-fi", "password", "internet", "network"],
            "DIRECTIONS": ["directions", "how to get", "address", "location", "gps", "lost"],
            "MAINTENANCE": ["broken", "not working", "problem", "issue", "heat", "ac", "hot water"],
            "AMENITIES": ["pool", "hot tub", "grill", "tv", "remote", "towels"],
            "NOISE_COMPLAINT": ["noise", "loud", "quiet hours", "neighbors"],
            "EMERGENCY": ["emergency", "urgent", "help", "911"],
        }
        
        for intent, keywords in intent_keywords.items():
            if any(keyword in body_lower for keyword in keywords):
                self.log.info("intent_classified", intent=intent, message_id=message.message_id)
                return intent
        
        return "GENERAL"
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Factory function for dependency injection
def get_twilio_adapter() -> TwilioAdapter:
    """Get Twilio adapter instance"""
    return TwilioAdapter()
