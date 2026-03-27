"""
Property model - Represents a rental property (cabin, cottage, etc.)
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.models.media import PropertyImage


class Property(Base):
    """Rental Property model"""
    
    __tablename__ = "properties"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Property Details
    name = Column(String(255), unique=True, nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    property_type = Column(String(50), nullable=False)  # cabin, cottage, house
    bedrooms = Column(Integer, nullable=False)
    bathrooms = Column(DECIMAL(3, 1), nullable=False)
    max_guests = Column(Integer, nullable=False)
    address = Column(Text)
    latitude = Column(DECIMAL(10, 8))
    longitude = Column(DECIMAL(11, 8))
    
    # Access & Connectivity
    wifi_ssid = Column(String(255))
    wifi_password = Column(String(255))
    access_code_type = Column(String(50))  # keypad, lockbox, smart_lock
    access_code_location = Column(Text)
    parking_instructions = Column(Text)
    
    # Pricing / rates from PMS
    rate_card = Column(JSONB)
    availability = Column(JSONB)

    # Housekeeping defaults
    default_housekeeper_id = Column(UUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="SET NULL"))
    default_clean_minutes = Column(Integer)
    streamline_checklist_id = Column(String(100))

    # Property amenities (cached from Streamline GetPropertyAmenities)
    amenities = Column(JSONB)

    # Vector Embedding (stored in Qdrant fgp_knowledge, reference here)
    qdrant_point_id = Column(UUID(as_uuid=True))

    # Metadata
    streamline_property_id = Column(String(100), index=True)
    ota_metadata = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    owner_id = Column(String(100))
    owner_name = Column(String(255))
    owner_balance = Column(JSONB)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    reservations = relationship("Reservation", back_populates="prop")
    work_orders = relationship("WorkOrder", back_populates="prop")
    guestbook_guides = relationship("GuestbookGuide", back_populates="prop")
    default_housekeeper = relationship("StaffUser", foreign_keys=[default_housekeeper_id])
    images = relationship(
        "PropertyImage",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    tax_links = relationship(
        "PropertyTax",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    fee_links = relationship(
        "PropertyFee",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    stay_restrictions = relationship(
        "PropertyStayRestriction",
        back_populates="prop",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Property {self.name}>"
