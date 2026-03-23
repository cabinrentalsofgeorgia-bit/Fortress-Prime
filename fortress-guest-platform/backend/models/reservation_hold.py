"""
ReservationHold — short-lived checkout lock for a property/date range.

Serialized via pg_advisory_xact_lock per property; overlaps prevented by
partial EXCLUDE constraint on active holds.
"""
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship, synonym

from backend.core.database import Base
from backend.core.time import utc_now


class ReservationHold(Base):
    __tablename__ = "reservation_holds"
    __table_args__ = (
        CheckConstraint("check_out_date > check_in_date", name="ck_reservation_holds_date_order"),
        CheckConstraint(
            "status IN ('active', 'expired', 'converted')",
            name="ck_reservation_holds_status",
        ),
        Index("ix_reservation_holds_property_dates", "property_id", "check_in_date", "check_out_date"),
        Index("ix_reservation_holds_status_expires", "status", "expires_at"),
        Index("ix_reservation_holds_payment_intent_id", "payment_intent_id"),
        Index("ix_reservation_holds_session_id", "session_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_id = Column(String(255), nullable=False, index=True)
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)
    check_in = synonym("check_in_date")
    check_out = synonym("check_out_date")
    num_guests = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    amount_total = Column(Numeric(12, 2), nullable=True)
    quote_snapshot = Column(JSONB, nullable=True)
    payment_intent_id = Column(String(255), nullable=True, index=True)
    special_requests = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property = relationship("Property", lazy="joined")
    guest = relationship("Guest", lazy="joined")
