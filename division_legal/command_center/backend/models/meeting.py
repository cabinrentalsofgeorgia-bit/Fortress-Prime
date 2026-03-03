"""
Meeting model — every meeting, call, or consultation.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, Text, Integer, Date, Boolean, Numeric,
    TIMESTAMP, ARRAY, ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = {"schema": "legal_cmd"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    matter_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.matters.id"))
    attorney_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.attorneys.id"))
    title = Column(String(255), nullable=False)
    meeting_type = Column(String(30), default="in_person")
    meeting_date = Column(TIMESTAMP(timezone=True), nullable=False)
    duration_minutes = Column(Integer)
    location = Column(String(255))
    attendees = Column(Text)
    summary = Column(Text)
    action_items = Column(Text)
    key_decisions = Column(Text)
    documents_discussed = Column(Text)
    billable = Column(Boolean, default=False)
    cost = Column(Numeric(10, 2))
    follow_up_date = Column(Date)
    follow_up_notes = Column(Text)
    tags = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    matter = relationship("Matter", back_populates="meetings", lazy="selectin")
    attorney = relationship("Attorney", back_populates="meetings", lazy="selectin")
