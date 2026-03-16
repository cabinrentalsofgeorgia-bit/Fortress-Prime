"""
Analytics and tracking models
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import relationship

from backend.core.database import Base


class AnalyticsEvent(Base):
    """Analytics Event Tracking"""
    
    __tablename__ = "analytics_events"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Event
    event_type = Column(String(100), nullable=False, index=True)
    # message_sent, message_received, ai_response, guide_viewed, etc
    
    # Context (Foreign Keys)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    
    # Data
    event_data = Column(JSONB)
    
    # Session
    session_id = Column(UUID(as_uuid=True))
    user_agent = Column(Text)
    ip_address = Column(INET)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    
    # Relationships
    guest = relationship("Guest")
    reservation = relationship("Reservation")
    prop = relationship("Property")
    
    def __repr__(self) -> str:
        return f"<AnalyticsEvent {self.event_type}>"
