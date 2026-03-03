"""
Pydantic V2 Domain Models - Strict Typing

All data flowing through the system MUST conform to these schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class MessageIntent(str, Enum):
    """Guest message intent classification"""

    WIFI_QUESTION = "wifi_question"
    ACCESS_CODE_REQUEST = "access_code_request"
    CHECKIN_QUESTION = "checkin_question"
    CHECKOUT_QUESTION = "checkout_question"
    MAINTENANCE_REQUEST = "maintenance_request"
    AMENITY_QUESTION = "amenity_question"
    UNKNOWN = "unknown"


class MessageStatus(str, Enum):
    """SMS delivery status"""

    RECEIVED = "received"        # Inbound message received
    QUEUED = "queued"            # Outbound message queued
    SENT = "sent"                # Outbound message sent
    DELIVERED = "delivered"      # Outbound message delivered
    FAILED = "failed"            # Message failed to send
    UNDELIVERABLE = "undeliverable"  # Phone number invalid


class Guest(BaseModel):
    """Guest entity from PMS"""

    guest_id: str = Field(..., description="PMS guest identifier")
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone_number: str = Field(..., pattern=r"^\+1\d{10}$")
    language_preference: str = Field(default="en", pattern=r"^[a-z]{2}$")

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Ensure E.164 format"""
        if not v.startswith("+1"):
            raise ValueError("Phone must be E.164 format (+1XXXXXXXXXX)")
        return v


class Reservation(BaseModel):
    """Property Management System reservation"""

    reservation_id: str = Field(..., description="PMS confirmation code")
    guest: Guest
    property_name: str = Field(..., description="Cabin/unit name")
    unit_id: str = Field(..., description="Internal unit identifier")
    checkin_date: datetime
    checkout_date: datetime
    status: str = Field(
        ...,
        pattern=r"^(confirmed|checked_in|checked_out|cancelled)$",
    )
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        """Check if reservation is currently active"""
        now = datetime.now()
        return (
            self.status in ["confirmed", "checked_in"]
            and self.checkin_date <= now <= self.checkout_date
        )


class AccessCode(BaseModel):
    """Door lock access code"""

    code: str = Field(..., min_length=4, max_length=8)
    unit_id: str
    reservation_id: str
    valid_from: datetime
    valid_until: datetime
    created_at: datetime

    @property
    def is_valid(self) -> bool:
        """Check if code is currently valid"""
        now = datetime.now()
        return self.valid_from <= now <= self.valid_until


class Message(BaseModel):
    """Normalized guest message (SMS)"""

    message_id: str = Field(..., description="Unique message identifier")
    from_phone: str = Field(..., pattern=r"^\+1\d{10}$")
    to_phone: str = Field(..., pattern=r"^\+1\d{10}$")
    body: str = Field(..., min_length=1, max_length=1600)
    received_at: datetime
    trace_id: str = Field(..., description="Correlation ID for observability")
    raw_payload: Optional[dict] = Field(
        default=None,
        description="Original webhook payload for debugging",
    )


class MessageResponse(BaseModel):
    """Outbound SMS response"""

    message_id: str
    status: MessageStatus
    body: str = Field(..., min_length=1)
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    trace_id: str
    provider: str = Field(..., description="ruebarue|twilio|crog_ai")
    metadata: Optional[dict] = Field(
        default=None,
        description="Provider-specific response data",
    )


class StranglerRouteDecision(BaseModel):
    """
    The Strangler Pattern Router Decision
    
    This model captures WHERE a request was routed and WHY.
    Critical for observability and incremental migration.
    """

    trace_id: str
    intent: MessageIntent
    route_to: str = Field(
        ...,
        pattern=r"^(legacy|ai|shadow)$",
        description="Routing decision",
    )
    reason: str = Field(..., description="Why this route was chosen")
    feature_flags: dict = Field(
        ...,
        description="Feature flag state at decision time",
    )
    reservation_found: bool
    timestamp: datetime


class ShadowResult(BaseModel):
    """
    Shadow Mode Comparison Result
    
    Captures divergence between Legacy and AI responses for analysis.
    """

    trace_id: str
    legacy_response: MessageResponse
    ai_response: MessageResponse
    responses_match: bool
    divergence_details: Optional[str] = None
    comparison_timestamp: datetime
