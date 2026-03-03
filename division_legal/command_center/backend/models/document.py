"""
Document model — references to documents linked to matters.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Text, TIMESTAMP, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": "legal_cmd"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    matter_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.matters.id"))
    title = Column(String(255), nullable=False)
    doc_type = Column(String(50))
    file_path = Column(Text)
    file_url = Column(Text)
    description = Column(Text)
    uploaded_by = Column(String(100), default="owner")
    tags = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    matter = relationship("Matter", back_populates="documents")
