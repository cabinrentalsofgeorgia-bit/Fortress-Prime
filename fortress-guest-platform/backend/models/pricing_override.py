"""
Sovereign pricing override ledger for human-approved yield actions.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.core.time import utc_now


class PricingOverride(Base):
    __tablename__ = "pricing_overrides"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_pricing_overrides_date_order"),
        CheckConstraint(
            "adjustment_percentage >= -100.00 AND adjustment_percentage <= 100.00",
            name="ck_pricing_overrides_adjustment_range",
        ),
        Index(
            "ix_pricing_overrides_property_dates",
            "property_id",
            "start_date",
            "end_date",
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
    adjustment_percentage = Column(Numeric(6, 2), nullable=False)
    reason = Column(String(500), nullable=False)
    approved_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property = relationship("Property", lazy="joined")
