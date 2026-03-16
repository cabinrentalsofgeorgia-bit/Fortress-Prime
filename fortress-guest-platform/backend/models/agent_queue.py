"""
Agent queue models:
- AgentResponseQueue (legacy review queue)
- AgentQueue (Hunter outbound sales queue)
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class AgentResponseQueue(Base):
    """Pending AI responses awaiting human review."""

    __tablename__ = "agent_response_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # The inbound message that triggered this response
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="SET NULL"),
        index=True,
    )
    reservation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="SET NULL"),
        index=True,
    )

    # Orchestrator classification
    intent = Column(String(50), index=True)
    sentiment_label = Column(String(30))
    sentiment_score = Column(Float)
    urgency_level = Column(Integer, default=0)

    # Proposed response
    proposed_response = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    action = Column(String(80))  # auto_reply_template, escalate, create_work_order, …
    escalation_reason = Column(Text)

    # Review workflow
    status = Column(String(30), nullable=False, default="pending", index=True)
    # pending, approved, edited, rejected, sent, expired
    reviewed_by = Column(String(100))
    reviewed_at = Column(TIMESTAMP)
    final_response = Column(Text)  # what was actually sent (may differ from proposed)
    sent_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"))

    # Decision metadata from the orchestrator
    decision_metadata = Column(JSONB, default=dict)

    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    inbound_message = relationship("Message", foreign_keys=[message_id])
    guest = relationship("Guest")
    reservation = relationship("Reservation")
    sent_message = relationship("Message", foreign_keys=[sent_message_id])

    def __repr__(self) -> str:
        return f"<AgentResponseQueue {self.status} conf={self.confidence}>"


class AgentQueue(Base):
    """Reactivation Hunter outbound queue with HITL approval workflow."""

    __tablename__ = "agent_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review','approved','edited','rejected','sending','delivered','failed')",
            name="ck_agent_queue_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)

    original_ai_draft = Column(Text, nullable=False)
    final_human_message = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pending_review", index=True)

    twilio_sid = Column(String(128), nullable=True, index=True)
    error_log = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    guest = relationship("Guest")
    prop = relationship("Property")

    def __repr__(self) -> str:
        return f"<AgentQueue status={self.status} twilio_sid={self.twilio_sid}>"
