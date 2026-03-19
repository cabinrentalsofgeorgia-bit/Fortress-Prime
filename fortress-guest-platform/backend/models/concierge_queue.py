"""
Concierge queue model used by inbound SMS concierge workflow.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class ConciergeQueue(Base):
    __tablename__ = "concierge_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review','approved','rejected','sent','failed')",
            name="ck_concierge_queue_status",
        ),
        Index("ix_concierge_queue_status_created", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    guest_phone = Column(String(40), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    inbound_message = Column(Text, nullable=False)
    retrieved_context = Column(JSONB, nullable=False, default=dict)
    ai_draft_reply = Column(Text, default="")
    reviewed_by = Column(String(120))
    review_note = Column(Text)
    sent_at = Column(DateTime)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="pending_review", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

