"""
Reactivation Hunter queue models.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class HunterQueueEntry(Base):
    __tablename__ = "hunter_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','processing','sent','failed','cancelled')",
            name="ck_hunter_queue_status",
        ),
        UniqueConstraint("session_fp", name="uq_hunter_queue_session_fp"),
        Index("ix_hunter_queue_status_created", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_fp = Column(String(128), nullable=False, unique=True, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    guest_phone = Column(String(40), index=True)
    guest_email = Column(String(255), index=True)
    campaign = Column(String(120), nullable=False, default="reactivation")
    payload = Column(JSONB, nullable=False, default=dict)
    score = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="queued", index=True)
    last_error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class HunterRun(Base):
    __tablename__ = "hunter_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trigger = Column(String(120), nullable=False, default="manual")
    campaign = Column(String(120), nullable=False, default="reactivation")
    stats = Column(JSONB, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)
