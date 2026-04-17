"""
StreamlinePayloadVault — Enterprise data vault for Streamline API payloads.

Every raw JSON response from Streamline VRS is persisted unmutated in this
table before any parsing, filtering, or transformation occurs.  This provides
an immutable audit trail for trust accounting reconciliation and forensic
debugging of Streamline data discrepancies.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class StreamlinePayloadVault(Base):
    __tablename__ = "streamline_payload_vault"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id = Column(String(100), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    raw_payload = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<StreamlinePayloadVault {self.event_type} {self.id}>"
