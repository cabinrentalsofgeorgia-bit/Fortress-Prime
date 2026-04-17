"""
Property model - Represents a rental property (cabin, cottage, etc.)
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, Enum as SqlEnum, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey, text
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
    county = Column(String(100))
    city_limits = Column(Boolean, default=False, server_default="false")
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
    cleaning_fee = Column(DECIMAL(10, 2))

    # Housekeeping defaults
    default_housekeeper_id = Column(UUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="SET NULL"))
    default_clean_minutes = Column(Integer)
    streamline_checklist_id = Column(String(100))

    # Property amenities (cached from Streamline GetPropertyAmenities)
    amenities = Column(JSONB)

    # Vector Embedding (stored in Qdrant fgp_knowledge, reference here)
    qdrant_point_id = Column(UUID(as_uuid=True))

    # Legacy content fields (scraped from Drupal / Streamline)
    rates_notes = Column(Text)
    video_urls = Column(JSONB)

    # Streamline property group (location_area_name from GetPropertyList).
    # Nullable permanently — offboarded properties legitimately have no group.
    # Backfilled by backfill_property_data_from_streamline().
    property_group = Column(String(100), nullable=True)

    # Property city, state abbreviation, postal code — separate from `address`
    # (which holds only the street). Backfilled by backfill_property_data_from_streamline().
    # Used by the PDF renderer to assemble the full address line:
    #   "{address} {city} {state} {postal_code}"
    city = Column(String(100), nullable=True)
    state = Column(String(50), nullable=True)
    postal_code = Column(String(20), nullable=True)

    # Metadata
    streamline_property_id = Column(String(100), index=True)
    ota_metadata = Column(JSONB, nullable=False, server_default="{}")
    owner_id = Column(String(100))
    owner_name = Column(String(255))
    owner_balance = Column(JSONB)
    is_active = Column(Boolean, default=True)
    # Distinguishes actively-renting properties from pre-launch / paused / offboarded ones.
    # Only 'active' properties generate owner statements.
    renting_state = Column(
        SqlEnum(
            "active", "pre_launch", "paused", "offboarded",
            name="property_renting_state",
            create_constraint=False,  # type already created by migration
        ),
        nullable=False,
        server_default="active",
    )
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    reservations = relationship("Reservation", back_populates="prop")
    work_orders = relationship("WorkOrder", back_populates="prop")
    guestbook_guides = relationship("GuestbookGuide", back_populates="prop")
    # Legacy mappers may still be loaded from bytecode via run.py's .pyc fallback.
    # Keep their reverse relationships defined so unrelated ORM queries, including
    # login, do not fail during mapper configuration.
    tax_links = relationship("PropertyTax", back_populates="property")
    fee_links = relationship("PropertyFee", back_populates="property")
    images = relationship("PropertyImage", back_populates="property")
    stay_restrictions = relationship("PropertyStayRestriction", back_populates="prop")
    pricing_overrides = relationship("PricingOverride", back_populates="property")
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
