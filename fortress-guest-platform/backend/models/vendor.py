"""
Vendor — contractor and service-provider directory.

Tracks vendors (HVAC, plumbing, electrical, etc.) for work order assignment.
Work orders can reference a vendor via assigned_vendor_id FK.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from backend.core.database import Base


class Vendor(Base):
    """Contractor / service-provider directory entry."""

    __tablename__ = "vendors"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    trade = Column(String(80), nullable=True)   # hvac, plumbing, electrical, landscaping, etc.
    phone = Column(String(40), nullable=True)
    email = Column(String(255), nullable=True)
    insurance_expiry = Column(Date, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    hourly_rate = Column(Numeric(8, 2), nullable=True)
    # Geographic regions this vendor covers
    regions = Column(JSONB, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Vendor {self.name!r} trade={self.trade} active={self.active}>"
