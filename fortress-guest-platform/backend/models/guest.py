"""
Guest model - Enterprise-grade guest profile management
SURPASSES: Streamline VRS CRM, RueBaRue contacts, Breezeway guest data

Features beyond ALL competitors:
- 360° guest profile with identity verification
- Loyalty tiers with automatic progression
- Risk scoring for property protection
- Value scoring for revenue optimization
- Emergency contacts and vehicle tracking
- Guest preferences and special requests
- Blacklist and flag management
- Source attribution and campaign tracking
- Full address with geocoding ready
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy import (
    Column, String, Boolean, Integer, DECIMAL, Date, Text,
    TIMESTAMP, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import enum

from backend.core.database import Base


class GuestTier(str, enum.Enum):
    """Loyalty tier levels"""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"


class VerificationStatus(str, enum.Enum):
    """Identity verification states"""
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Guest(Base):
    """
    Enterprise Guest Profile
    
    BETTER THAN Streamline VRS: Full CRM with scoring, loyalty, verification
    BETTER THAN RueBaRue: Rich profile data, not just a phone number
    """
    
    __tablename__ = "guests"
    
    # ── Primary Key ──
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # ── Contact Information ──
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    phone_number_secondary = Column(String(20))
    email = Column(String(255), index=True)
    email_secondary = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))
    
    # ── Address ──
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(50))
    postal_code = Column(String(20))
    country = Column(String(2), default="US")
    
    # ── Demographics ──
    date_of_birth = Column(Date)
    
    # ── Emergency Contact ──
    emergency_contact_name = Column(String(200))
    emergency_contact_phone = Column(String(20))
    emergency_contact_relationship = Column(String(50))
    
    # ── Vehicle Information ──
    vehicle_make = Column(String(50))
    vehicle_model = Column(String(50))
    vehicle_color = Column(String(30))
    vehicle_plate = Column(String(20))
    vehicle_state = Column(String(5))
    
    # ── Communication Preferences ──
    language_preference = Column(String(10), default="en")
    opt_in_marketing = Column(Boolean, default=True)
    opt_in_sms = Column(Boolean, default=True)
    opt_in_email = Column(Boolean, default=True)
    preferred_contact_method = Column(String(20), default="sms")
    quiet_hours_start = Column(String(5))  # "22:00"
    quiet_hours_end = Column(String(5))    # "08:00"
    timezone = Column(String(50), default="America/New_York")
    
    # ── Identity Verification ──
    verification_status = Column(
        String(20), default="unverified", index=True
    )
    verification_method = Column(String(50))  # id_upload, stripe_identity, manual
    verified_at = Column(TIMESTAMP)
    id_document_type = Column(String(50))  # drivers_license, passport, state_id
    id_expiration_date = Column(Date)
    
    # ── Loyalty Program ──
    loyalty_tier = Column(String(20), default="bronze", index=True)
    loyalty_points = Column(Integer, default=0)
    loyalty_enrolled_at = Column(TIMESTAMP)
    lifetime_stays = Column(Integer, default=0)
    lifetime_nights = Column(Integer, default=0)
    lifetime_revenue = Column(DECIMAL(12, 2), default=0)
    
    # ── Scoring ──
    value_score = Column(Integer, default=50)    # 0-100 (revenue potential)
    risk_score = Column(Integer, default=10)     # 0-100 (damage/problem potential)
    satisfaction_score = Column(Integer)          # 0-100 (based on surveys/reviews)
    
    # ── Guest Preferences (stored as structured JSON) ──
    preferences = Column(JSONB, default={})
    # {
    #   "bed_type": "king",
    #   "floor_preference": "upper",
    #   "pillow_type": "firm",
    #   "temperature": "cool",
    #   "dietary": ["vegetarian"],
    #   "special_occasions": [{"type": "anniversary", "date": "2026-06-15"}],
    #   "pet_info": {"has_pets": true, "type": "dog", "breed": "labrador", "name": "Max"},
    #   "accessibility": ["ground_floor", "grab_bars"],
    #   "amenity_favorites": ["hot_tub", "fireplace", "game_room"]
    # }
    
    # ── Special Requests / Notes ──
    special_requests = Column(Text)
    internal_notes = Column(Text)
    staff_notes = Column(Text)  # Visible only to management
    
    # ── Flags & Status ──
    is_vip = Column(Boolean, default=False, index=True)
    is_blacklisted = Column(Boolean, default=False, index=True)
    blacklist_reason = Column(Text)
    blacklisted_at = Column(TIMESTAMP)
    blacklisted_by = Column(String(100))
    is_do_not_contact = Column(Boolean, default=False)
    requires_supervision = Column(Boolean, default=False)
    
    # ── Source & Attribution ──
    guest_source = Column(String(50), index=True)  # airbnb, vrbo, direct, referral, repeat
    referral_source = Column(String(255))  # specific referral detail
    first_booking_source = Column(String(50))
    acquisition_campaign = Column(String(100))
    
    # ── Legacy Analytics (backward compat) ──
    total_stays = Column(Integer, default=0)
    total_messages_sent = Column(Integer, default=0)
    total_messages_received = Column(Integer, default=0)
    average_rating = Column(DECIMAL(3, 2))
    last_stay_date = Column(Date)
    
    # ── External IDs ──
    streamline_guest_id = Column(String(100))
    airbnb_guest_id = Column(String(100))
    vrbo_guest_id = Column(String(100))
    booking_com_guest_id = Column(String(100))
    stripe_customer_id = Column(String(100))
    
    # ── Tags (flexible categorization) ──
    tags = Column(ARRAY(String))
    notes = Column(Text)  # backward compat
    
    # ── Timestamps ──
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_contacted_at = Column(TIMESTAMP)
    last_activity_at = Column(TIMESTAMP)
    
    # ── Relationships ──
    reservations = relationship("Reservation", back_populates="guest", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="guest", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="guest")
    reviews = relationship("GuestReview", back_populates="guest", cascade="all, delete-orphan")
    surveys = relationship("GuestSurvey", back_populates="guest", cascade="all, delete-orphan")
    agreements = relationship("RentalAgreement", back_populates="guest", cascade="all, delete-orphan")
    activities = relationship("GuestActivity", back_populates="guest", cascade="all, delete-orphan")
    verifications = relationship("GuestVerification", back_populates="guest", cascade="all, delete-orphan")
    
    # ── Computed Properties ──
    
    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or "Guest"
    
    @property
    def is_repeat_guest(self) -> bool:
        return (self.total_stays or 0) > 1
    
    @property
    def is_verified(self) -> bool:
        return self.verification_status == "verified"
    
    @property
    def display_tier(self) -> str:
        tier = self.loyalty_tier or "bronze"
        tier_labels = {
            "bronze": "Bronze",
            "silver": "Silver",
            "gold": "Gold",
            "platinum": "Platinum",
            "diamond": "Diamond",
        }
        return tier_labels.get(tier, "Bronze")
    
    @property
    def full_address(self) -> Optional[str]:
        parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            f"{self.state} {self.postal_code}" if self.state else self.postal_code,
            self.country if self.country != "US" else None,
        ]
        return ", ".join(p for p in parts if p)
    
    @property
    def vehicle_description(self) -> Optional[str]:
        if not self.vehicle_make:
            return None
        parts = [self.vehicle_color, self.vehicle_make, self.vehicle_model]
        desc = " ".join(p for p in parts if p)
        if self.vehicle_plate:
            desc += f" ({self.vehicle_plate})"
        return desc
    
    def calculate_loyalty_tier(self) -> str:
        """Calculate tier based on stays and revenue"""
        stays = self.lifetime_stays or 0
        revenue = float(self.lifetime_revenue or 0)
        
        if stays >= 20 or revenue >= 50000:
            return "diamond"
        elif stays >= 10 or revenue >= 25000:
            return "platinum"
        elif stays >= 5 or revenue >= 10000:
            return "gold"
        elif stays >= 2 or revenue >= 3000:
            return "silver"
        return "bronze"
    
    def calculate_value_score(self) -> int:
        """Calculate guest value score (0-100) based on revenue and behavior"""
        score = 50  # Base
        
        stays = self.lifetime_stays or 0
        revenue = float(self.lifetime_revenue or 0)
        avg_rating = float(self.average_rating or 3)
        
        # Revenue component (0-30 points)
        if revenue >= 20000:
            score += 30
        elif revenue >= 10000:
            score += 25
        elif revenue >= 5000:
            score += 20
        elif revenue >= 2000:
            score += 15
        elif revenue >= 500:
            score += 10
        
        # Repeat stay component (0-20 points)
        score += min(stays * 4, 20)
        
        # Rating component (-10 to +10)
        score += int((avg_rating - 3) * 5)
        
        # VIP bonus
        if self.is_vip:
            score += 10
        
        return max(0, min(100, score))
    
    def calculate_risk_score(self) -> int:
        """Calculate guest risk score (0-100)"""
        score = 10  # Base (low risk)
        
        # No verification = higher risk
        if self.verification_status != "verified":
            score += 15
        
        # New guest (no history) = moderate risk
        if (self.total_stays or 0) == 0:
            score += 10
        
        # Blacklist history
        if self.is_blacklisted:
            score = 100
        
        # Low rating from property = higher risk
        avg = float(self.average_rating or 3)
        if avg < 2:
            score += 20
        elif avg < 3:
            score += 10
        
        return max(0, min(100, score))
    
    def __repr__(self) -> str:
        return f"<Guest {self.full_name} ({self.phone_number}) [{self.loyalty_tier}]>"
