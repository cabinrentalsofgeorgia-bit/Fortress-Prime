"""
Matter model — legal subjects, cases, disputes, or projects being tracked.
"""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, Numeric, TIMESTAMP, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Matter(Base):
    __tablename__ = "matters"
    __table_args__ = {"schema": "legal_cmd"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String(255), nullable=False)
    reference_code = Column(String(50), unique=True)
    category = Column(String(50), nullable=False)
    status = Column(String(30), default="open")
    priority = Column(String(20), default="normal")
    description = Column(Text)
    attorney_id = Column(UUID(as_uuid=True), ForeignKey("legal_cmd.attorneys.id"))
    opposing_party = Column(String(255))
    opposing_counsel = Column(String(255))
    amount_at_stake = Column(Numeric(12, 2))
    outcome = Column(Text)
    outcome_date = Column(Date)
    next_action = Column(Text)
    next_action_date = Column(Date)
    tags = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    attorney = relationship("Attorney", back_populates="matters", lazy="selectin")
    meetings = relationship("Meeting", back_populates="matter", lazy="selectin")
    timeline = relationship("TimelineEntry", back_populates="matter", lazy="selectin", order_by="TimelineEntry.created_at.desc()")
    documents = relationship("Document", back_populates="matter", lazy="selectin")
