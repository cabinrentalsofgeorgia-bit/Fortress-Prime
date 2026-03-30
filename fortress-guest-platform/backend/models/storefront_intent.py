"""
First-party, consented storefront intent signals (coarse events only).

See docs/architecture/sovereign-intent-engine-boundaries.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class StorefrontIntentEvent(Base):
    __tablename__ = "storefront_intent_events"
    __table_args__ = (
        Index("ix_storefront_intent_session_created", "session_fp", "created_at"),
        Index("ix_storefront_intent_created", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_fp = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    consent_marketing = Column(Boolean, nullable=False, default=False, server_default="false")
    property_slug = Column(String(255), nullable=True)
    meta = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
