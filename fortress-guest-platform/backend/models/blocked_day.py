"""
BlockedDay model — Persists calendar blocks fetched from Streamline Phase 3.

Captures reservation blocks, owner holds, and maintenance windows so
availability can be computed from a local table instead of on-the-fly
Streamline API calls.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Date, ForeignKey, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class BlockedDay(Base):
    __tablename__ = "blocked_days"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "start_date", "end_date", "block_type",
            name="uq_blocked_days_prop_dates_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    block_type = Column(String(50), default="reservation")
    confirmation_code = Column(String(50), nullable=True)
    source = Column(String(20), default="streamline")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    property = relationship("Property", lazy="joined")
