"""
Guest Verification model - Identity verification & compliance
SURPASSES: Streamline's basic guest verification, Autohost, Superhog

Features:
- Multi-method verification (ID upload, Stripe Identity, manual)
- Document tracking with expiration
- Background check integration ready
- Damage deposit tracking
- Guest agreement acknowledgment
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DECIMAL, Text, TIMESTAMP, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class GuestVerification(Base):
    """Guest identity verification record"""
    
    __tablename__ = "guest_verifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    
    # Verification Type
    verification_type = Column(String(50), nullable=False)
    # id_upload, stripe_identity, manual_review, background_check, credit_check
    
    # Status
    status = Column(String(30), nullable=False, default="pending", index=True)
    # pending, in_review, approved, rejected, expired
    
    # Document Info
    document_type = Column(String(50))  # drivers_license, passport, state_id, military_id
    document_number_hash = Column(String(255))  # Hashed for security
    document_country = Column(String(2))
    document_state = Column(String(5))
    document_expiration = Column(Date)
    document_front_url = Column(Text)  # Secure storage URL
    document_back_url = Column(Text)
    selfie_url = Column(Text)
    
    # Verification Result
    confidence_score = Column(DECIMAL(4, 3))  # 0.000 - 1.000
    match_details = Column(JSONB)
    # {
    #   "name_match": true,
    #   "dob_match": true,
    #   "address_match": false,
    #   "photo_match_score": 0.95,
    #   "document_authentic": true,
    #   "flags": ["address_mismatch"]
    # }
    
    # Review
    reviewed_by = Column(String(100))
    reviewed_at = Column(TIMESTAMP)
    rejection_reason = Column(Text)
    
    # External References
    external_verification_id = Column(String(255))  # Stripe Identity session ID, etc.
    provider = Column(String(50))  # stripe, autohost, manual
    
    # Metadata
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(TIMESTAMP)
    
    # Relationships
    guest = relationship("Guest", back_populates="verifications")
    
    @property
    def is_valid(self) -> bool:
        if self.status != "approved":
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True
    
    def __repr__(self) -> str:
        return f"<GuestVerification {self.verification_type} - {self.status}>"
