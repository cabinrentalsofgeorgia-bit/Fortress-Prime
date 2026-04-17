"""Godhead Memory Ledger — AI-learned pricing rules from shadow discrepancy analysis."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Float, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class LearnedRule(Base):
    __tablename__ = "learned_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    rule_name = Column(String(255), nullable=False)
    trigger_condition = Column(JSONB, nullable=False)
    adjustment_type = Column(String(20), nullable=False)
    adjustment_value = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), nullable=False, default="pending_approval", index=True)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
