"""
PendingSync — Offline booking buffer for Streamline API resilience.

When a guest completes a Stripe checkout, the reservation is created locally.
If the Streamline PMS push fails (timeout, API down, rate limit), the booking
intent is saved here for automatic retry by the Hermes sync worker.

This ensures a guest NEVER sees a failed checkout due to Streamline downtime.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Date, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class PendingSync(Base):
    __tablename__ = "pending_sync"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), nullable=False)
    sync_type = Column(String(50), nullable=False, default="create_reservation")
    status = Column(String(30), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)
