"""Persisted AI operational intelligence (NemoClaw outputs keyed by Kafka-driven task_id)."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class AiInsight(Base):
    __tablename__ = "ai_insights"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_ai_insights_task_id"),
        Index("ix_ai_insights_event_type", "event_type"),
        Index("ix_ai_insights_reference_id", "reference_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(String(255), nullable=False)
    event_type = Column(String(128), nullable=False)
    reference_id = Column(String(255), nullable=False)
    insight_payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
