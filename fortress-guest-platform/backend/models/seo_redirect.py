"""
Typed SEO redirect records managed by API tools.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Boolean, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class SeoRedirect(Base):
    __tablename__ = "seo_redirects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_path = Column(String(1024), nullable=False, unique=True, index=True)
    destination_path = Column(String(1024), nullable=False)
    is_permanent = Column(Boolean, nullable=False, default=True)
    reason = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        code = "301" if self.is_permanent else "302"
        return f"<SeoRedirect {self.source_path} -> {self.destination_path} ({code})>"
