"""
Local SEO citation audit tracking models.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class CitationRecord(Base):
    """Directory listing audit snapshot for NAP consistency tracking."""

    __tablename__ = "citation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    directory_domain = Column(String(255), nullable=False, unique=True, index=True)
    profile_url = Column(String(1000))
    found_name = Column(String(500))
    found_address = Column(String(1000))
    found_phone = Column(String(100))
    match_status = Column(String(30), nullable=False, default="missing", index=True)
    last_audited_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<CitationRecord domain={self.directory_domain} status={self.match_status}>"
