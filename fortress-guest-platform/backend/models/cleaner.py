"""
Cleaner — structured cleaner/housekeeper directory.

Provides a first-class table for managing cleaner profiles, rates, and
property/region assignments. Tasks in housekeeping_tasks can reference
a cleaner via the assigned_cleaner_id FK.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from backend.core.database import Base


class Cleaner(Base):
    """Directory entry for a cleaning contractor or employee."""

    __tablename__ = "cleaners"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    phone = Column(String(40), nullable=True)
    email = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    per_clean_rate = Column(Numeric(8, 2), nullable=True)
    hourly_rate = Column(Numeric(8, 2), nullable=True)
    # List of property UUIDs this cleaner covers (denormalized for fast lookup)
    property_ids = Column(JSONB, nullable=False, default=list)
    # Geographic regions (e.g. ["blue_ridge", "ellijay"])
    regions = Column(JSONB, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Cleaner {self.name!r} active={self.active}>"
