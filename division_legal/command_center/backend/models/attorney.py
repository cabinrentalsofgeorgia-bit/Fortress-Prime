"""
Attorney model — every attorney or firm you've engaged.
"""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, Integer, Numeric, TIMESTAMP, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Attorney(Base):
    __tablename__ = "attorneys"
    __table_args__ = {"schema": "legal_cmd"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    firm_name = Column(String(255))
    specialty = Column(String(100))
    email = Column(String(255))
    phone = Column(String(30))
    address = Column(Text)
    website = Column(String(255))
    bar_number = Column(String(50))
    bar_state = Column(String(10))
    hourly_rate = Column(Numeric(10, 2))
    retainer_amount = Column(Numeric(10, 2))
    retainer_status = Column(String(20), default="none")
    engagement_date = Column(Date)
    status = Column(String(20), default="active")
    rating = Column(Integer)
    notes = Column(Text)
    tags = Column(ARRAY(String))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    matters = relationship("Matter", back_populates="attorney", lazy="selectin")
    meetings = relationship("Meeting", back_populates="attorney", lazy="selectin")
