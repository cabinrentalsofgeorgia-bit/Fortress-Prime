"""
Work Order model - Maintenance and issue tracking
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DECIMAL, Text, TIMESTAMP, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class WorkOrder(Base):
    """Work Order/Maintenance Ticket model"""
    
    __tablename__ = "work_orders"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_number = Column(String(50), unique=True, nullable=False)
    
    # Foreign Keys
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    reported_via_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"))
    
    # Issue Details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    # hvac, plumbing, electrical, hot_tub, appliance, other
    
    priority = Column(String(20), nullable=False, default="medium", index=True)
    # low, medium, high, urgent
    
    # Status
    status = Column(String(50), nullable=False, default="open", index=True)
    # open, in_progress, waiting_parts, completed, cancelled
    
    # Assignment
    assigned_to = Column(String(255))
    # Structured vendor FK (migration f3a91b8c2e47)
    legacy_assigned_to = Column(String(255))
    assigned_vendor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_at = Column(TIMESTAMP)
    
    # Resolution
    resolved_at = Column(TIMESTAMP)
    resolution_notes = Column(Text)
    cost_amount = Column(DECIMAL(10, 2))
    
    # Photos
    photo_urls = Column(ARRAY(String))
    
    # Vector Embedding (stored in Qdrant fgp_knowledge, reference here)
    qdrant_point_id = Column(UUID(as_uuid=True))

    # Metadata
    created_by = Column(String(100))  # 'guest', 'staff', 'ai_detected'
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prop = relationship("Property", back_populates="work_orders")
    reservation = relationship("Reservation", back_populates="work_orders")
    guest = relationship("Guest", back_populates="work_orders")
    reported_via_message = relationship("Message", foreign_keys=[reported_via_message_id])
    
    def __repr__(self) -> str:
        return f"<WorkOrder {self.ticket_number} - {self.title}>"
