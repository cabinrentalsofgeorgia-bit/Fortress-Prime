"""
Intelligence distillation queue models.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum as SQLEnum, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class DistillationStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DistillationQueue(Base):
    __tablename__ = "distillation_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_module = Column(String(120), nullable=False, index=True)
    source_ref = Column(String(255), nullable=False, index=True)
    input_payload = Column(JSONB, nullable=False, default=dict)
    output_payload = Column(JSONB, nullable=False, default=dict)
    status = Column(
        SQLEnum(DistillationStatus, name="distillation_status", native_enum=False),
        nullable=False,
        default=DistillationStatus.QUEUED,
        index=True,
    )
    error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
