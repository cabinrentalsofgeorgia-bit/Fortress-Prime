"""
Guestbook models - Digital guides and extras marketplace
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class GuestbookGuide(Base):
    """Digital Guestbook Guide (Property or Area info)"""
    
    __tablename__ = "guestbook_guides"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Foreign Key (NULL = area guide shared across properties)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    
    # Guide Details
    title = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    guide_type = Column(String(50), nullable=False, index=True)  # home_guide, area_guide, emergency
    category = Column(String(50))  # wifi, rules, amenities, restaurants, etc
    
    # Content
    content = Column(Text, nullable=False)  # Markdown format
    icon = Column(String(50))  # emoji or icon class
    
    # Display
    display_order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True, index=True)
    visibility_rules = Column(JSONB)  # {'show_before_checkin': true, 'show_days': [-1, 0, 1]}
    
    # Metadata
    view_count = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prop = relationship("Property", back_populates="guestbook_guides")
    
    def __repr__(self) -> str:
        return f"<GuestbookGuide {self.title}>"


class Extra(Base):
    """Extras Marketplace Item (Upsells)"""
    
    __tablename__ = "extras"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Product
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(50))  # firewood, late_checkout, early_checkin, cleaning
    
    # Pricing
    price = Column(DECIMAL(10, 2), nullable=False)
    currency = Column(String(3), default="USD")
    
    # Availability
    is_available = Column(Boolean, default=True, index=True)
    properties = Column(ARRAY(UUID(as_uuid=True)))  # Array of property IDs (NULL = all properties)
    
    # Display
    image_url = Column(Text)
    display_order = Column(Integer, default=0)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    orders = relationship("ExtraOrder", back_populates="extra")
    
    def __repr__(self) -> str:
        return f"<Extra {self.name} - ${self.price}>"


class ExtraOrder(Base):
    """Extra Order (Guest purchase)"""
    
    __tablename__ = "extra_orders"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Foreign Keys
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    extra_id = Column(UUID(as_uuid=True), ForeignKey("extras.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Order Details
    quantity = Column(Integer, default=1)
    unit_price = Column(DECIMAL(10, 2), nullable=False)
    total_price = Column(DECIMAL(10, 2), nullable=False)
    
    # Status
    status = Column(String(50), nullable=False, default="pending", index=True)
    # pending, confirmed, fulfilled, cancelled, refunded
    
    # Fulfillment
    fulfilled_at = Column(TIMESTAMP)
    notes = Column(Text)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    reservation = relationship("Reservation", back_populates="extra_orders")
    extra = relationship("Extra", back_populates="orders")
    
    def __repr__(self) -> str:
        return f"<ExtraOrder {self.extra.name if self.extra else 'Unknown'} x{self.quantity}>"
