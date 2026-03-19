"""
Message models - SMS communication tracking
"""
import enum
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey, ARRAY, Time, Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class ApprovalStatus(str, enum.Enum):
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"


class Message(Base):
    """SMS Message model"""
    
    __tablename__ = "messages"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id = Column(String(255), index=True)  # Twilio MessageSid
    
    # Foreign Keys
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    
    # Message Details
    direction = Column(String(20), nullable=False, index=True)  # inbound, outbound
    phone_from = Column(String(20), nullable=False, index=True)
    phone_to = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)
    
    # Classification (AI-powered)
    intent = Column(String(50), index=True)  # wifi_question, access_code, maintenance, etc
    sentiment = Column(String(20), index=True)  # positive, neutral, negative, urgent
    category = Column(String(50))  # info_request, complaint, booking, emergency
    
    # Status
    status = Column(String(50), nullable=False, default="sent")
    # draft, queued, sent, delivered, failed, received

    # HITL approval gate
    approval_status = Column(
        SqlEnum(ApprovalStatus, name="message_approval_status"),
        nullable=False,
        default=ApprovalStatus.approved,
        index=True,
    )
    agent_reasoning = Column(Text)
    
    # AI Response
    is_auto_response = Column(Boolean, default=False)
    ai_confidence = Column(DECIMAL(4, 3))  # 0.0-1.0
    requires_human_review = Column(Boolean, default=False)
    human_reviewed_at = Column(TIMESTAMP)
    human_reviewed_by = Column(String(100))
    
    # Delivery
    sent_at = Column(TIMESTAMP)
    delivered_at = Column(TIMESTAMP)
    read_at = Column(TIMESTAMP)
    error_code = Column(String(50))
    error_message = Column(Text)
    
    # Metadata
    provider = Column(String(50), default="twilio")
    cost_amount = Column(DECIMAL(8, 4))
    num_segments = Column(Integer, default=1)
    trace_id = Column(UUID(as_uuid=True))
    extra_data = Column("metadata", JSONB)  # Provider-specific data
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    
    # Relationships
    guest = relationship("Guest", back_populates="messages")
    reservation = relationship("Reservation", back_populates="messages")
    
    def __repr__(self) -> str:
        return f"<Message {self.direction} {self.phone_from} -> {self.phone_to}>"


class MessageTemplate(Base):
    """Message Template for automated campaigns"""
    
    __tablename__ = "message_templates"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), unique=True, nullable=False)
    category = Column(String(50), nullable=False, index=True)
    
    # Template
    subject = Column(String(255))
    body = Column(Text, nullable=False)
    variables = Column(ARRAY(String))  # ['first_name', 'property_name', 'check_in_date']
    
    # Scheduling
    trigger_type = Column(String(50))  # time_based, event_based, manual
    trigger_offset_days = Column(Integer)  # -7 = 7 days before check_in
    trigger_time = Column(Time)  # 09:00:00 = 9am
    
    # Settings
    is_active = Column(Boolean, default=True, index=True)
    send_priority = Column(Integer, default=0)
    language = Column(String(10), default="en")
    
    # Metadata
    usage_count = Column(Integer, default=0)
    last_used_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    scheduled_messages = relationship("ScheduledMessage", back_populates="template")
    
    def __repr__(self) -> str:
        return f"<MessageTemplate {self.name}>"


class ScheduledMessage(Base):
    """Scheduled Message (future send)"""
    
    __tablename__ = "scheduled_messages"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Foreign Keys
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("message_templates.id", ondelete="CASCADE"), index=True)
    
    # Schedule
    scheduled_for = Column(TIMESTAMP, nullable=False, index=True)
    sent_at = Column(TIMESTAMP)
    
    # Content (rendered template)
    phone_to = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)
    
    # Status
    status = Column(String(50), nullable=False, default="pending", index=True)
    # pending, sent, failed, cancelled
    
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"))
    error_message = Column(Text)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationships
    guest = relationship("Guest")
    reservation = relationship("Reservation", back_populates="scheduled_messages")
    template = relationship("MessageTemplate", back_populates="scheduled_messages")
    message = relationship("Message", foreign_keys=[message_id])
    
    def __repr__(self) -> str:
        return f"<ScheduledMessage {self.status} for {self.scheduled_for}>"
