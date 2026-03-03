"""
Timeline model — running record of events, actions, and notes on any matter.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Text, TIMESTAMP, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class TimelineEntry(Base):
    __tablename__ = "timeline"
    __table_args__ = {"schema": "legal_cmd"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    matter_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.matters.id"), nullable=False)
    entry_type = Column(String(30), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    entered_by = Column(String(100), default="owner")
    importance = Column(String(20), default="normal")
    related_meeting_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.meetings.id"))
    related_attorney_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.attorneys.id"))
    document_ref = Column(Text)
    tags = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    matter = relationship("Matter", back_populates="timeline")
    meeting = relationship("Meeting", lazy="selectin")
    attorney = relationship("Attorney", lazy="selectin")
