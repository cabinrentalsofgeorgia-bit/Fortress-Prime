"""
PropertyStayRestriction — Strike 18 sovereign yield rules mirrored from Streamline or staff-managed.

``must_check_in_on_day`` / ``must_check_out_on_day`` use Python ``date.weekday()``:
Monday = 0 … Sunday = 6 (match Streamline export mapping in sync jobs when ingesting).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, ForeignKey, SmallInteger, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base

_WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class PropertyStayRestriction(Base):
    """Blackouts and stay-shape rules overlapping a date window for one property."""

    __tablename__ = "property_stay_restrictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_blackout = Column(Boolean, nullable=False, default=False)
    must_check_in_on_day = Column(SmallInteger, nullable=True)
    must_check_out_on_day = Column(SmallInteger, nullable=True)
    source = Column(String(32), nullable=False, default="sovereign")
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    prop = relationship("Property", back_populates="stay_restrictions")

    @property
    def must_check_in_day_name(self) -> str | None:
        if self.must_check_in_on_day is None:
            return None
        d = int(self.must_check_in_on_day)
        if 0 <= d <= 6:
            return _WEEKDAY_NAMES[d]
        return "configured weekday"

    @property
    def must_check_out_day_name(self) -> str | None:
        if self.must_check_out_on_day is None:
            return None
        d = int(self.must_check_out_on_day)
        if 0 <= d <= 6:
            return _WEEKDAY_NAMES[d]
        return "configured weekday"
