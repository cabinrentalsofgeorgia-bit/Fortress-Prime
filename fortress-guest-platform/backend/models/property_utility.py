"""
PropertyUtility + UtilityReading models
Tracks service accounts (ISP, electric, water, gas, etc.) and daily cost readings.
Credentials are stored encrypted at rest via pgcrypto or application-level Fernet.
"""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import (
    Column, String, Boolean, Text, TIMESTAMP, Date, Numeric,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


SERVICE_TYPES = [
    "internet",
    "electric",
    "water",
    "gas",
    "sewer",
    "trash",
    "propane",
    "cable_tv",
    "security",
    "pest_control",
    "landscaping",
    "pool_spa",
    "other",
]


class PropertyUtility(Base):
    __tablename__ = "property_utilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    service_type = Column(String(50), nullable=False)
    provider_name = Column(String(255), nullable=False)
    account_number = Column(String(255))
    account_holder = Column(String(255))

    # Portal credentials (encrypted at app level before storage)
    portal_url = Column(Text)
    portal_username = Column(Text)
    portal_password_enc = Column(Text)

    contact_phone = Column(String(50))
    contact_email = Column(String(255))
    notes = Column(Text)

    monthly_budget = Column(Numeric(10, 2))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    readings = relationship("UtilityReading", back_populates="utility", cascade="all, delete-orphan")


class UtilityReading(Base):
    __tablename__ = "utility_readings"
    __table_args__ = (
        UniqueConstraint("utility_id", "reading_date", name="uq_reading_per_day"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    utility_id = Column(UUID(as_uuid=True), ForeignKey("property_utilities.id", ondelete="CASCADE"), nullable=False, index=True)

    reading_date = Column(Date, nullable=False, default=date.today)
    cost = Column(Numeric(10, 2), nullable=False)
    usage_amount = Column(Numeric(12, 4))
    usage_unit = Column(String(30))
    notes = Column(Text)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    utility = relationship("PropertyUtility", back_populates="readings")
