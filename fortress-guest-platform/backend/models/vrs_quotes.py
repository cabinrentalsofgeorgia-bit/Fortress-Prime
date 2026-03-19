"""
Guest quote models used by checkout and Stripe webhook reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DECIMAL, Column, Date, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class GuestQuoteStatus:
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class GuestQuote(Base):
    __tablename__ = "guest_quotes"
    __table_args__ = (
        Index("ix_guest_quotes_status_created", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    target_property_id = Column(String(255), nullable=False, index=True)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(
        SQLEnum(
            GuestQuoteStatus.PENDING,
            GuestQuoteStatus.ACCEPTED,
            GuestQuoteStatus.REJECTED,
            GuestQuoteStatus.EXPIRED,
            name="guest_quote_status",
            native_enum=True,
            create_constraint=False,
            validate_strings=True,
        ),
        nullable=False,
        default=GuestQuoteStatus.PENDING,
        index=True,
    )
    campaign = Column(String(100), nullable=False, default="direct")
    target_keyword = Column(String(255))

    guest_name = Column(String(255))
    guest_email = Column(String(255))
    guest_phone = Column(String(40))

    check_in = Column(Date)
    check_out = Column(Date)
    nights = Column(Integer)
    adults = Column(Integer, nullable=False, default=2)
    children = Column(Integer, nullable=False, default=0)
    pets = Column(Integer, nullable=False, default=0)

    currency = Column(String(10), nullable=False, default="USD")
    base_rent = Column(DECIMAL(12, 2), nullable=False, default=Decimal("0.00"))
    taxes = Column(DECIMAL(12, 2), nullable=False, default=Decimal("0.00"))
    fees = Column(DECIMAL(12, 2), nullable=False, default=Decimal("0.00"))
    total_amount = Column(DECIMAL(12, 2), nullable=False, default=Decimal("0.00"))
    base_price = Column(Float, nullable=False, default=0.0)
    ai_adjusted_price = Column(Float, nullable=False, default=0.0)
    sovereign_narrative = Column(Text, nullable=False, default="")

    quote_breakdown = Column(JSONB, nullable=False, default=dict)
    source_snapshot = Column(JSONB, nullable=False, default=dict)

    stripe_payment_link_url = Column(String(1024))
    stripe_payment_link_id = Column(String(255))

    note = Column(Text)
    expires_at = Column(TIMESTAMP, nullable=False, default=lambda: datetime.utcnow() + timedelta(hours=24))
    accepted_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    property = relationship("Property", foreign_keys=[property_id])

    def __repr__(self) -> str:
        return f"<GuestQuote id={self.id} status={self.status}>"

