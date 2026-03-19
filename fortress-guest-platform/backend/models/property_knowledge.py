"""
Property knowledge snippets for concierge retrieval.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class PropertyKnowledge(Base):
    __tablename__ = "property_knowledge"
    __table_args__ = (
        Index("ix_property_knowledge_prop_cat_updated", "property_id", "category", "updated_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    category = Column(String(80), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String(120), nullable=False, default="manual")
    tags = Column(JSONB, nullable=False, default=list)
    confidence = Column(String(20), nullable=False, default="medium")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)

