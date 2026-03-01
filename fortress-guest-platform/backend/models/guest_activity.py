"""
Guest Activity model - Complete activity timeline
SURPASSES: All competitors (nobody has a comprehensive guest activity timeline)

Features:
- Full audit trail of every guest interaction
- Unified timeline across all touchpoints
- Category-based filtering
- Staff attribution
- Related entity linking (reservation, message, work order, etc.)
- Searchable activity history
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class GuestActivity(Base):
    """
    Guest activity timeline entry
    
    Tracks every interaction, change, and event related to a guest.
    Creates a complete 360° audit trail.
    """
    
    __tablename__ = "guest_activities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Guest
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Activity Classification
    activity_type = Column(String(50), nullable=False, index=True)
    # reservation_created, reservation_cancelled, checked_in, checked_out,
    # message_sent, message_received, review_submitted, review_received,
    # survey_completed, agreement_signed, verification_completed,
    # work_order_created, extra_purchased, profile_updated,
    # tag_added, tag_removed, note_added, blacklisted, un_blacklisted,
    # loyalty_tier_changed, payment_received, refund_issued,
    # guestbook_viewed, support_ticket_opened, staff_interaction
    
    category = Column(String(30), nullable=False, index=True)
    # booking, communication, feedback, verification, maintenance,
    # financial, profile, loyalty, operational
    
    # Description
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Related Entities (polymorphic references)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"))
    message_id = Column(UUID(as_uuid=True))
    review_id = Column(UUID(as_uuid=True))
    survey_id = Column(UUID(as_uuid=True))
    agreement_id = Column(UUID(as_uuid=True))
    work_order_id = Column(UUID(as_uuid=True))
    
    # Context
    performed_by = Column(String(100))  # staff email, "system", "guest", "ai"
    performed_by_type = Column(String(20))  # staff, guest, system, ai
    
    # Extra Data
    extra_data = Column("metadata", JSONB)
    # Flexible JSON for activity-specific data:
    # reservation_created: {"confirmation_code": "CRG-12345", "property": "Eagle's Nest"}
    # loyalty_tier_changed: {"old_tier": "silver", "new_tier": "gold"}
    # message_received: {"intent": "wifi_question", "sentiment": "neutral"}
    
    # Importance (for filtering)
    importance = Column(String(10), default="normal")
    # low, normal, high, critical
    
    # Visibility
    is_visible_to_guest = Column(String(5), default="false")
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    
    # Relationships
    guest = relationship("Guest", back_populates="activities")
    
    def __repr__(self) -> str:
        return f"<GuestActivity {self.activity_type}: {self.title}>"
