"""
Rental Agreement model - E-signature & document management
SURPASSES: Streamline's StreamSign, DocuSign basic integration

Features:
- Digital rental agreement generation per reservation
- E-signature with legally-binding tracking
- Custom agreement templates per property
- Automatic sending via trigger system
- Damage waiver / pet addendum support
- Signature audit trail
- IP and device tracking for legal compliance
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class AgreementTemplate(Base):
    """Reusable rental agreement template"""
    
    __tablename__ = "agreement_templates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    agreement_type = Column(String(50), nullable=False, index=True)
    # rental_agreement, pet_addendum, damage_waiver, liability_waiver, 
    # cancellation_policy, house_rules, pool_waiver
    
    # Template Content (with variable placeholders)
    content_markdown = Column(Text, nullable=False)
    # Uses {{variable}} syntax:
    # "This Rental Agreement is between {{property_owner}} and {{guest_name}}..."
    
    # Variables required
    required_variables = Column(JSONB)
    # ["guest_name", "property_name", "check_in_date", "check_out_date", "total_amount"]
    
    # Settings
    is_active = Column(Boolean, default=True, index=True)
    requires_signature = Column(Boolean, default=True)
    requires_initials = Column(Boolean, default=False)
    auto_send = Column(Boolean, default=True)
    send_days_before_checkin = Column(Integer, default=7)
    
    # Applicable properties (NULL = all)
    property_ids = Column(JSONB)  # list of property UUIDs
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    agreements = relationship("RentalAgreement", back_populates="template")
    
    def __repr__(self) -> str:
        return f"<AgreementTemplate {self.name}>"


class RentalAgreement(Base):
    """Individual rental agreement instance"""
    
    __tablename__ = "rental_agreements"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Context
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("agreement_templates.id", ondelete="SET NULL"), index=True)
    
    # Agreement Type
    agreement_type = Column(String(50), nullable=False)
    
    # Rendered Content (with variables filled in)
    rendered_content = Column(Text, nullable=False)
    
    # Status
    status = Column(String(30), nullable=False, default="draft", index=True)
    # draft, sent, viewed, signed, expired, cancelled
    
    # Sending
    sent_at = Column(TIMESTAMP)
    sent_via = Column(String(20))  # email, sms, portal
    agreement_url = Column(Text)  # Unique signing URL
    expires_at = Column(TIMESTAMP)
    
    # Viewing
    first_viewed_at = Column(TIMESTAMP)
    view_count = Column(Integer, default=0)
    
    # Signature
    signed_at = Column(TIMESTAMP)
    signature_type = Column(String(30))  # typed, drawn, click_to_sign
    signature_data = Column(Text)  # Base64 of drawn signature or typed name
    signer_name = Column(String(200))
    signer_email = Column(String(255))
    
    # Initials (if required)
    initials_data = Column(Text)
    initials_pages = Column(JSONB)  # Pages where initials were placed
    
    # Legal compliance / audit trail
    signer_ip_address = Column(String(45))
    signer_user_agent = Column(Text)
    signer_device_fingerprint = Column(String(255))
    consent_recorded = Column(Boolean, default=False)
    
    # PDF (generated after signing)
    pdf_url = Column(Text)
    pdf_generated_at = Column(TIMESTAMP)
    
    # Reminders
    reminder_count = Column(Integer, default=0)
    last_reminder_at = Column(TIMESTAMP)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    guest = relationship("Guest", back_populates="agreements")
    reservation = relationship("Reservation", back_populates="agreements", foreign_keys=[reservation_id])
    prop = relationship("Property", foreign_keys=[property_id])
    template = relationship("AgreementTemplate", back_populates="agreements")
    
    @property
    def is_signed(self) -> bool:
        return self.status == "signed" and self.signed_at is not None
    
    @property
    def is_expired(self) -> bool:
        return self.expires_at and datetime.utcnow() > self.expires_at and self.status != "signed"
    
    @property
    def needs_reminder(self) -> bool:
        if self.status not in ("sent", "viewed"):
            return False
        if self.reminder_count >= 3:
            return False
        return True
    
    def __repr__(self) -> str:
        return f"<RentalAgreement {self.agreement_type} - {self.status}>"
