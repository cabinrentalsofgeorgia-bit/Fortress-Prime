"""
Sovereign guest ledger model.

This keeps the transactional booking identity local to fortress_prod while
preserving a few compatibility aliases used by older services.
"""
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship, synonym

from backend.core.database import Base


class Guest(Base):
    __tablename__ = "guests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True, index=True)
    phone_number_secondary = Column(String(20), nullable=True)
    email_secondary = Column(String(255), nullable=True)
    address_line1 = Column(String(255), nullable=True)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    state = Column(String(100), nullable=True, index=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    language_preference = Column(String(16), nullable=True)
    preferred_contact_method = Column(String(32), nullable=True)
    opt_in_marketing = Column(Boolean, nullable=True)
    opt_in_sms = Column(Boolean, nullable=True)
    opt_in_email = Column(Boolean, nullable=True)
    quiet_hours_start = Column(String(16), nullable=True)
    quiet_hours_end = Column(String(16), nullable=True)
    timezone = Column(String(64), nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)
    emergency_contact_relationship = Column(String(100), nullable=True)
    vehicle_make = Column(String(100), nullable=True)
    vehicle_model = Column(String(100), nullable=True)
    vehicle_color = Column(String(100), nullable=True)
    vehicle_plate = Column(String(32), nullable=True)
    vehicle_state = Column(String(32), nullable=True)
    special_requests = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    staff_notes = Column(Text, nullable=True)
    preferences = Column(JSONB, nullable=True)
    tags = Column(ARRAY(String()), nullable=True)
    verification_status = Column(String(20), nullable=False, default="unverified", index=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verification_method = Column(String(64), nullable=True)
    loyalty_tier = Column(String(20), nullable=False, default="bronze", index=True)
    loyalty_points = Column(Integer, nullable=False, default=0)
    loyalty_enrolled_at = Column(DateTime(timezone=True), nullable=True)
    lifetime_stays = Column(Integer, nullable=False, default=0)
    total_stays = Column(Integer, nullable=False, default=0)
    lifetime_nights = Column(Integer, nullable=False, default=0)
    lifetime_revenue = Column(Numeric(12, 2), nullable=False, default=0)
    average_rating = Column(Numeric(4, 2), nullable=True)
    last_stay_date = Column(Date, nullable=True, index=True)
    value_score = Column(Integer, nullable=True, index=True)
    risk_score = Column(Integer, nullable=True, index=True)
    satisfaction_score = Column(Integer, nullable=True)
    is_vip = Column(Boolean, nullable=False, default=False, index=True)
    is_blacklisted = Column(Boolean, nullable=False, default=False, index=True)
    blacklist_reason = Column(Text, nullable=True)
    blacklisted_by = Column(String(255), nullable=True)
    blacklisted_at = Column(DateTime(timezone=True), nullable=True)
    requires_supervision = Column(Boolean, nullable=False, default=False)
    is_do_not_contact = Column(Boolean, nullable=False, default=False)
    guest_source = Column(String(100), nullable=True, index=True)
    first_booking_source = Column(String(100), nullable=True)
    referral_source = Column(String(100), nullable=True)
    acquisition_campaign = Column(String(255), nullable=True)
    streamline_guest_id = Column(String(100), nullable=True, index=True)
    airbnb_guest_id = Column(String(100), nullable=True)
    vrbo_guest_id = Column(String(100), nullable=True)
    booking_com_guest_id = Column(String(100), nullable=True)
    stripe_customer_id = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Legacy compatibility alias still referenced across the backend.
    phone_number = synonym("phone")

    reservations = relationship("Reservation", back_populates="guest", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="guest", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="guest")
    reviews = relationship("GuestReview", back_populates="guest", cascade="all, delete-orphan")
    surveys = relationship("GuestSurvey", back_populates="guest", cascade="all, delete-orphan")
    agreements = relationship("RentalAgreement", back_populates="guest", cascade="all, delete-orphan")
    activities = relationship("GuestActivity", back_populates="guest", cascade="all, delete-orphan")
    verifications = relationship("GuestVerification", back_populates="guest", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or "Guest"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "verified"

    @property
    def display_tier(self) -> str:
        tier = (self.loyalty_tier or "bronze").strip().lower()
        return tier.capitalize()

    @property
    def full_address(self) -> str | None:
        parts = [
            (self.address_line1 or "").strip(),
            (self.address_line2 or "").strip(),
            (self.city or "").strip(),
            (self.state or "").strip(),
            (self.postal_code or "").strip(),
            (self.country or "").strip(),
        ]
        rendered = ", ".join(part for part in parts if part)
        return rendered or None

    @property
    def vehicle_description(self) -> str | None:
        parts = [
            (self.vehicle_color or "").strip(),
            (self.vehicle_make or "").strip(),
            (self.vehicle_model or "").strip(),
        ]
        rendered = " ".join(part for part in parts if part)
        return rendered or None

    @property
    def is_repeat_guest(self) -> bool:
        return (self.total_stays or self.lifetime_stays or 0) > 1

    def calculate_value_score(self) -> int:
        score = 20
        score += min(30, int((self.total_stays or self.lifetime_stays or 0)) * 8)
        score += min(35, int(float(self.lifetime_revenue or 0) / 500))
        if self.average_rating is not None:
            score += min(15, int(float(self.average_rating) * 3))
        return max(0, min(100, score))

    def calculate_risk_score(self) -> int:
        if self.is_blacklisted:
            return 100
        score = 10
        if self.verification_status != "verified":
            score += 15
        if not self.phone_number:
            score += 10
        return max(0, min(100, score))

    def calculate_loyalty_tier(self) -> str:
        stays = self.total_stays or self.lifetime_stays or 0
        revenue = float(self.lifetime_revenue or 0)
        if stays >= 20 or revenue >= 50000:
            return "diamond"
        if stays >= 10 or revenue >= 25000:
            return "platinum"
        if stays >= 5 or revenue >= 10000:
            return "gold"
        if stays >= 2 or revenue >= 3000:
            return "silver"
        return "bronze"

    def __repr__(self) -> str:
        return f"<Guest {self.full_name} ({self.email})>"
