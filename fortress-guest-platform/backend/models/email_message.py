"""
EmailMessage — email-channel communication row, analog of Message (SMS).

direction='inbound'  — from inquirer, captured by the IMAP watcher
direction='outbound' — reply drafted by AI, approved by staff, sent via SMTP
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, ForeignKey,
    Numeric, String, Text, TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class EmailMessage(Base):
    __tablename__ = "email_messages"

    __table_args__ = (
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_email_messages_direction",
        ),
        CheckConstraint(
            "approval_status IN ('pending_approval', 'approved', 'rejected', "
            "'sent', 'send_failed', 'no_draft_needed')",
            name="ck_email_messages_approval_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Linkages
    inquirer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("email_inquirers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reservation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    in_reply_to_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("email_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Email envelope
    direction = Column(String(20), nullable=False, index=True)
    email_from = Column(String(255), nullable=False)
    email_to = Column(String(255), nullable=False)
    email_cc = Column(Text)
    subject = Column(Text)
    body_text = Column(Text, nullable=False)
    body_excerpt = Column(Text)

    # IMAP source identity (inbound only)
    imap_uid = Column(BigInteger, index=True)
    imap_message_id = Column(Text)
    received_at = Column(TIMESTAMP(timezone=True), index=True)

    # AI / concierge
    intent = Column(String(50), index=True)
    sentiment = Column(String(20))
    category = Column(String(50))
    ai_draft = Column(Text)
    ai_confidence = Column(Numeric(4, 3))
    ai_meta = Column(JSONB)

    # HITL workflow
    approval_status = Column(String(30), nullable=False, default="pending_approval", index=True)
    requires_human_review = Column(Boolean, nullable=False, default=True)
    human_reviewed_at = Column(TIMESTAMP(timezone=True))
    human_reviewed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    human_edited_body = Column(Text)

    # Send / delivery
    sent_at = Column(TIMESTAMP(timezone=True))
    smtp_message_id = Column(Text)
    error_code = Column(String(50))
    error_message = Column(Text)

    # Attachment / Vision enrichment (Deployment C)
    has_attachments = Column(Boolean, nullable=False, default=False)
    image_descriptions = Column(JSONB)  # [{"filename": str, "description": str}]

    # Audit
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    extra_data = Column(JSONB)

    # Relationships
    inquirer = relationship("EmailInquirer", back_populates="messages")
    guest = relationship("Guest", foreign_keys=[guest_id])
    reservation = relationship("Reservation", foreign_keys=[reservation_id])
    reviewer = relationship("StaffUser", foreign_keys=[human_reviewed_by])
    # Self-referential: message this is a reply to
    parent_message = relationship(
        "EmailMessage",
        foreign_keys=[in_reply_to_message_id],
        remote_side="EmailMessage.id",
        back_populates="replies",
    )
    # Self-referential: replies sent in response to this message
    replies = relationship(
        "EmailMessage",
        foreign_keys="EmailMessage.in_reply_to_message_id",
        back_populates="parent_message",
    )

    def __repr__(self) -> str:
        return f"<EmailMessage {self.direction} from={self.email_from} status={self.approval_status}>"
