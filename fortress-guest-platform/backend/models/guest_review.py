"""
Guest Review model - Bidirectional review system
SURPASSES: Streamline's basic review requests, RueBaRue's Google review links

Features:
- Guest reviews OF properties (post-stay feedback)
- Property manager reviews OF guests (internal scoring)
- Multi-category ratings (cleanliness, communication, etc.)
- Review response/reply system
- Auto-publish to website and OTAs
- Review solicitation tracking
- Sentiment analysis integration
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class GuestReview(Base):
    """
    Bidirectional review system
    
    direction='guest_to_property' = Guest reviewing their stay
    direction='property_to_guest' = Manager reviewing the guest
    """
    
    __tablename__ = "guest_reviews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Context
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Direction
    direction = Column(String(30), nullable=False, index=True)
    # guest_to_property, property_to_guest
    
    # Overall Rating
    overall_rating = Column(Integer, nullable=False)  # 1-5
    
    # Category Ratings (guest reviewing property)
    cleanliness_rating = Column(Integer)   # 1-5
    accuracy_rating = Column(Integer)      # 1-5 (listing accuracy)
    communication_rating = Column(Integer)  # 1-5
    location_rating = Column(Integer)       # 1-5
    checkin_rating = Column(Integer)        # 1-5
    value_rating = Column(Integer)          # 1-5
    amenities_rating = Column(Integer)      # 1-5
    
    # Category Ratings (manager reviewing guest)
    house_rules_rating = Column(Integer)    # 1-5 (followed rules?)
    cleanliness_left_rating = Column(Integer)  # 1-5 (left property clean?)
    communication_guest_rating = Column(Integer)  # 1-5
    respect_rating = Column(Integer)        # 1-5 (respect for property)
    noise_rating = Column(Integer)          # 1-5 (noise compliance)
    checkout_compliance_rating = Column(Integer)  # 1-5
    
    # Written Review
    title = Column(String(255))
    body = Column(Text)
    
    # Response (from the other party)
    response_body = Column(Text)
    response_by = Column(String(100))
    response_at = Column(TIMESTAMP)
    
    # AI Analysis
    sentiment = Column(String(20))  # positive, neutral, negative, mixed
    sentiment_score = Column(DECIMAL(4, 3))
    key_phrases = Column(JSONB)  # ["great hot tub", "noisy neighbors", "beautiful view"]
    improvement_suggestions = Column(JSONB)  # AI-extracted actionable items
    
    # Publishing
    is_published = Column(Boolean, default=False, index=True)
    published_at = Column(TIMESTAMP)
    publish_to_website = Column(Boolean, default=True)
    publish_to_airbnb = Column(Boolean, default=False)
    publish_to_google = Column(Boolean, default=False)
    external_review_urls = Column(JSONB)  # {"google": "url", "airbnb": "url"}
    
    # Moderation
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(String(255))
    moderated_by = Column(String(100))
    moderated_at = Column(TIMESTAMP)
    
    # Solicitation tracking
    solicitation_sent_at = Column(TIMESTAMP)
    solicitation_method = Column(String(20))  # sms, email
    solicitation_template_id = Column(UUID(as_uuid=True))
    submitted_via = Column(String(30))  # sms_reply, web_form, email_link, manual
    
    # Source tracking
    streamline_feedback_id = Column(String(100))
    source = Column(String(50), default="manual")

    # Metadata
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    guest = relationship("Guest", back_populates="reviews")
    reservation = relationship("Reservation")
    
    @property
    def average_category_rating(self) -> float:
        """Average of all non-null category ratings"""
        if self.direction == "guest_to_property":
            ratings = [
                self.cleanliness_rating, self.accuracy_rating,
                self.communication_rating, self.location_rating,
                self.checkin_rating, self.value_rating, self.amenities_rating
            ]
        else:
            ratings = [
                self.house_rules_rating, self.cleanliness_left_rating,
                self.communication_guest_rating, self.respect_rating,
                self.noise_rating, self.checkout_compliance_rating
            ]
        valid = [r for r in ratings if r is not None]
        return sum(valid) / len(valid) if valid else 0
    
    @property
    def is_positive(self) -> bool:
        return self.overall_rating >= 4
    
    @property
    def needs_attention(self) -> bool:
        return self.overall_rating <= 2 or self.is_flagged
    
    def __repr__(self) -> str:
        return f"<GuestReview {self.direction} rating={self.overall_rating}>"
