"""Knowledge models for legacy RAG and sovereign pgvector retrieval."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, Column, ForeignKey, Integer, String, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.config import settings
from backend.core.database import Base


class KnowledgeBaseEntry(Base):
    """Knowledge Base Entry for AI/RAG"""
    
    __tablename__ = "knowledge_base_entries"
    
    # Primary Key
    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Classification
    category = Column(String(100), nullable=False, index=True)
    # property_info, area_info, policy, faq, troubleshooting
    
    # Content
    question = Column(Text)
    answer = Column(Text, nullable=False)
    keywords = Column(ARRAY(String))
    
    # Context (NULL = general knowledge for all properties)
    property_id = Column(PostgresUUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    
    # Vector Embedding (stored in Qdrant, reference here)
    qdrant_point_id = Column(PostgresUUID(as_uuid=True))
    
    # Usage
    usage_count = Column(Integer, default=0)
    helpful_count = Column(Integer, default=0)
    not_helpful_count = Column(Integer, default=0)
    last_used_at = Column(TIMESTAMP)
    
    # Metadata
    is_active = Column(Boolean, default=True, index=True)
    source = Column(String(100))  # manual, imported, ai_generated
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prop = relationship("Property")
    
    def __repr__(self) -> str:
        return f"<KnowledgeBaseEntry {self.category}>"


class PropertyKnowledgeChunk(Base):
    """Grounded property-scoped knowledge chunk stored in sovereign pgvector."""

    __tablename__ = "property_knowledge_chunks"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embed_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, default=datetime.utcnow)

    prop = relationship("Property")

    def __repr__(self) -> str:
        return f"<PropertyKnowledgeChunk property_id={self.property_id}>"
