"""
Pydantic schemas for the email HITL review API.

Mirrors backend/schemas/message_review.py for the email channel.
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EmailMessageReviewContext(BaseModel):
    message_id: UUID
    inquirer_id: UUID
    inquirer_email: str
    inquirer_name: Optional[str] = None
    guest_id: Optional[UUID] = None
    reservation_id: Optional[UUID] = None
    subject: Optional[str] = None
    body_text: str
    ai_draft: Optional[str] = None
    ai_confidence: Optional[float] = None
    intent: Optional[str] = None
    sentiment: Optional[str] = None
    received_at: Optional[datetime] = None
    created_at: datetime
    approval_status: Literal[
        "pending_approval", "approved", "rejected",
        "sent", "send_failed", "no_draft_needed",
    ]

    class Config:
        from_attributes = True


class ReviewActionResponse(BaseModel):
    message_id: UUID
    status: str
    action_timestamp: datetime
    reviewer_id: UUID
    smtp_message_id: Optional[str] = Field(
        None, description="SMTP message-ID header if approved and sent"
    )
