"""Channel mapping model — property → OTA external listing ID."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class ChannelMapping(Base):
    __tablename__ = "channel_mappings"
    __table_args__ = (
        UniqueConstraint("property_id", "channel", name="uq_channel_mappings_property_channel"),
        Index("ix_channel_mappings_property_id", "property_id"),
        Index("ix_channel_mappings_channel", "channel"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)           # 'channex', 'airbnb', 'vrbo', 'booking_com', 'ical'
    external_listing_id = Column(String(255), nullable=False)
    sync_status = Column(String(30), nullable=False, default="active")  # active | paused | error | pending
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    property = relationship("Property", lazy="select")

    def __repr__(self) -> str:
        return f"<ChannelMapping {self.channel}:{self.external_listing_id} property={self.property_id}>"
