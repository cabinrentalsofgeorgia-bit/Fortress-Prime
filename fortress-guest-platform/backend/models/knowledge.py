"""
Knowledge Base model - For AI/RAG
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, Text, TIMESTAMP, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class KnowledgeBaseEntry(Base):
    """Knowledge Base Entry for AI/RAG"""
    
    __tablename__ = "knowledge_base_entries"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Classification
    category = Column(String(100), nullable=False, index=True)
    # property_info, area_info, policy, faq, troubleshooting
    
    # Content
    question = Column(Text)
    answer = Column(Text, nullable=False)
    keywords = Column(ARRAY(String))
    
    # Context (NULL = general knowledge for all properties)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    
    # Vector Embedding (stored in Qdrant, reference here)
    qdrant_point_id = Column(UUID(as_uuid=True))
    
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
