"""
MessageQueue model — Human-in-the-loop copilot draft queue.

Each row represents a rendered email (subject + body) tied to a specific
Quote and EmailTemplate. The UniqueConstraint on (quote_id, template_id)
enforces DB-level idempotency: a guest can never have the same template
drafted or sent twice for the same quote.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, String, Text, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class MessageQueue(Base):
    __tablename__ = "message_queue"
    __table_args__ = (
        UniqueConstraint("quote_id", "template_id", name="uq_message_queue_quote_template"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    quote_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("email_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), nullable=False, default="drafted", index=True)
    rendered_subject = Column(String(1000), nullable=False, default="")
    rendered_body = Column(Text, nullable=False, default="")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    quote = relationship("Quote", lazy="joined")
    template = relationship("EmailTemplate", lazy="joined")

    def __repr__(self) -> str:
        return f"<MessageQueue {self.id} quote={self.quote_id} status={self.status}>"
