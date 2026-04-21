"""
EmailInquirer — email-channel contact analog of Guest.

Tracks people who contact us via email but may not yet have a phone-bearing
Guest row. When an inquirer books and provides a phone number they are linked
via guest_id.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class EmailInquirer(Base):
    __tablename__ = "email_inquirers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))

    # Forward linkage: set when this inquirer becomes a real guest
    guest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    inferred_party_size = Column(Integer)
    inferred_dates_text = Column(Text)

    opt_in_email = Column(Boolean, nullable=False, default=True)

    first_seen_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    inquiry_count = Column(Integer, nullable=False, default=1)

    # Relationships
    guest = relationship("Guest", foreign_keys=[guest_id])
    messages = relationship(
        "EmailMessage",
        back_populates="inquirer",
        cascade="all, delete-orphan",
        order_by="EmailMessage.received_at.desc()",
    )

    @property
    def full_name(self) -> str:
        if self.first_name or self.last_name:
            return f"{self.first_name or ''} {self.last_name or ''}".strip()
        return self.display_name or self.email

    def __repr__(self) -> str:
        return f"<EmailInquirer {self.email}>"
