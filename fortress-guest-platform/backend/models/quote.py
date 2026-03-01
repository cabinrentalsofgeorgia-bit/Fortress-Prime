"""
Quote / QuoteOption models — Multi-property pricing comparison for the Lead Engine.

A Quote is a time-limited pricing snapshot attached to a Lead.
Each Quote contains one or more QuoteOptions, each representing an
itemized price breakdown for a specific property and date range.

Financial columns use DECIMAL(12,2) per Rule 7 (Financial Data Governance).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Date, DECIMAL, TIMESTAMP, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(String(20), nullable=False, default="draft", index=True)
    payment_method = Column(String(20), nullable=True)

    expires_at = Column(TIMESTAMP)
    ai_drafted_email_body = Column(Text, nullable=True)
    ai_draft_model = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead = relationship("Lead", back_populates="quotes")
    options = relationship("QuoteOption", back_populates="quote", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Quote {self.id} lead={self.lead_id} options={len(self.options) if self.options else 0}>"


class QuoteOption(Base):
    __tablename__ = "quote_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    quote_id = Column(UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)

    base_rent = Column(DECIMAL(12, 2))
    taxes = Column(DECIMAL(12, 2))
    fees = Column(DECIMAL(12, 2))
    total_price = Column(DECIMAL(12, 2))
    booking_link = Column(String(500), nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    quote = relationship("Quote", back_populates="options")
    property = relationship("Property", lazy="joined")

    def __repr__(self) -> str:
        return f"<QuoteOption {self.property_id} ${self.total_price}>"
