"""
Lead model — Pre-booking prospect tracking for the Agentic Lead Engine.

Represents inbound inquiries from Streamline xLeads, OTA channels,
direct website forms, and SMS booking inquiries. Each Lead can have
multiple Quotes attached for multi-property comparison.
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class LeadStatus(str, enum.Enum):
    NEW = "new"
    ACTIVE = "active"
    COLD = "cold"
    DEAD = "dead"
    CONVERTED = "converted"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    streamline_lead_id = Column(String(100), unique=True, nullable=True, index=True)
    guest_name = Column(String(255))
    email = Column(String(255), index=True)
    phone = Column(String(20))
    guest_message = Column(Text)

    status = Column(String(20), nullable=False, default=LeadStatus.NEW.value, index=True)
    ai_score = Column(Integer, nullable=True)
    source = Column(String(50), index=True)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    quotes = relationship("Quote", back_populates="lead", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Lead {self.guest_name} ({self.email}) [{self.status}]>"
