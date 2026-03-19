from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MessageReviewContext(BaseModel):
    message_id: UUID
    guest_id: Optional[UUID] = None
    reservation_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    guest_name: Optional[str] = None
    property_name: Optional[str] = None
    reservation_confirmation_code: Optional[str] = None
    recipient_phone: str
    body: str
    agent_reasoning: Optional[str] = None
    created_at: datetime
    approval_status: Literal["pending_approval", "approved", "rejected"]

    class Config:
        from_attributes = True


class ReviewActionResponse(BaseModel):
    message_id: UUID
    status: str
    action_timestamp: datetime
    reviewer_id: UUID
    dispatch_sid: Optional[str] = Field(
        None, description="Twilio SID if approved and sent"
    )
