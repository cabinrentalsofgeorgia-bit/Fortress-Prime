"""
Reservation model - Represents a booking/reservation
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Boolean, Column, DECIMAL, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, synonym

from backend.core.database import Base
from backend.core.time import utc_now


class Reservation(Base):
    """Reservation/Booking model"""
    
    __tablename__ = "reservations"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    confirmation_code = Column(String(50), unique=True, nullable=False, index=True)
    
    # Foreign Keys
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    # Sovereign guest ledger fields
    guest_email = Column(String(255), nullable=False, index=True, default="", server_default="")
    guest_name = Column(String(255), nullable=False, default="", server_default="")
    guest_phone = Column(String(50), nullable=True)
    
    # Dates & Guests
    check_in_date = Column(Date, nullable=False, index=True)
    check_out_date = Column(Date, nullable=False, index=True)
    check_in = synonym("check_in_date")
    check_out = synonym("check_out_date")
    num_guests = Column(Integer, nullable=False)
    num_adults = Column(Integer)
    num_children = Column(Integer)
    num_pets = Column(Integer, default=0)
    special_requests = Column(Text)
    
    # Status
    status = Column(String(50), nullable=False, default="confirmed", index=True)
    # confirmed, checked_in, checked_out, cancelled, no_show
    
    # Access
    access_code = Column(String(20))
    access_code_valid_from = Column(DateTime(timezone=True))
    access_code_valid_until = Column(DateTime(timezone=True))
    
    # Booking Details
    booking_source = Column(String(100))  # airbnb, vrbo, direct, etc
    # True when Streamline's maketype_name == 'O' (owner-stay reservation).
    # Owner bookings contribute $0.00 to owner statements.
    is_owner_booking = Column(Boolean, nullable=False, default=False, server_default="false")
    total_amount = Column(DECIMAL(10, 2))
    paid_amount = Column(DECIMAL(10, 2))
    balance_due = Column(DECIMAL(10, 2))
    nightly_rate = Column(DECIMAL(10, 2))
    cleaning_fee = Column(DECIMAL(10, 2))
    pet_fee = Column(DECIMAL(10, 2))
    damage_waiver_fee = Column(DECIMAL(10, 2))
    service_fee = Column(DECIMAL(10, 2))
    tax_amount = Column(DECIMAL(10, 2))
    nights_count = Column(Integer)
    price_breakdown = Column(JSONB)
    currency = Column(String(3), default="USD")
    
    # Communication Tracking
    digital_guide_sent = Column(Boolean, default=False)
    pre_arrival_sent = Column(Boolean, default=False)
    access_info_sent = Column(Boolean, default=False)
    mid_stay_checkin_sent = Column(Boolean, default=False)
    checkout_reminder_sent = Column(Boolean, default=False)
    post_stay_followup_sent = Column(Boolean, default=False)
    
    # Ratings & Feedback
    guest_rating = Column(Integer)  # 1-5
    guest_feedback = Column(Text)
    internal_notes = Column(Text)
    
    # Streamline notes (synced from GetReservationNotes)
    streamline_notes = Column(JSONB)
    # Full price/payment detail from GetReservationPrice
    streamline_financial_detail = Column(JSONB)

    # Exact tax breakdown at booking time (from LedgerTaxBreakdown.to_dict())
    tax_breakdown = Column(JSONB)

    # Vector Embedding (stored in Qdrant fgp_knowledge, reference here)
    qdrant_point_id = Column(UUID(as_uuid=True))

    # Security Deposit
    security_deposit_required = Column(Boolean, default=False, server_default="false", nullable=False)
    security_deposit_amount = Column(Numeric(12, 2), default=500.00, server_default="500.00", nullable=False)
    security_deposit_status = Column(String(20), default="none", server_default="none", nullable=False)
    security_deposit_stripe_pi = Column(String(255))
    security_deposit_updated_at = Column(DateTime(timezone=True))
    security_deposit_payment_method_id = Column(String(255))

    # Metadata
    streamline_reservation_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    guest = relationship("Guest", back_populates="reservations")
    prop = relationship("Property", back_populates="reservations")
    messages = relationship("Message", back_populates="reservation")
    scheduled_messages = relationship("ScheduledMessage", back_populates="reservation")
    work_orders = relationship("WorkOrder", back_populates="reservation")
    extra_orders = relationship("ExtraOrder", back_populates="reservation")
    agreements = relationship("RentalAgreement", back_populates="reservation", foreign_keys="[RentalAgreement.reservation_id]")
    
    @staticmethod
    def _et_today():
        import pytz
        return datetime.now(pytz.timezone("America/New_York")).date()

    @property
    def is_current(self) -> bool:
        """Check if reservation is currently active"""
        today = self._et_today()
        return (
            self.status in ["confirmed", "checked_in"]
            and self.check_in_date <= today <= self.check_out_date
        )
    
    @property
    def is_arriving_today(self) -> bool:
        """Check if guest is arriving today"""
        return self.check_in_date == self._et_today() and self.status in ["confirmed", "checked_in"]
    
    @property
    def is_departing_today(self) -> bool:
        """Check if guest is departing today"""
        return self.check_out_date == self._et_today() and self.status in ["confirmed", "checked_in", "checked_out", "no_show"]
    
    @property
    def nights(self) -> int:
        """Calculate number of nights"""
        return (self.check_out_date - self.check_in_date).days
    
    def __repr__(self) -> str:
        return f"<Reservation {self.confirmation_code}>"
