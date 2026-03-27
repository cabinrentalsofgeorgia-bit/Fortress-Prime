"""SMS/email recovery sends for Strike 11 Enticer Swarm (idempotency + audit)."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class ConciergeRecoveryDispatch(Base):
    __tablename__ = "concierge_recovery_dispatches"
    __table_args__ = (
        Index("ix_crd_guest_channel_created", "guest_id", "channel", "created_at"),
        Index("ix_crd_session_fp", "session_fp"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_fp = Column(String(64), nullable=True)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(16), nullable=False)
    template_key = Column(String(64), nullable=False, server_default="abandon_cart_v1")
    body_preview = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, server_default="sent")
    provider_metadata = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
