"""
Links anonymized storefront session fingerprints to ledger guests after explicit booking.

Created only after a successful checkout hold (PI issued) when the browser supplies
the same first-party session UUID used for consented intent events.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class StorefrontSessionGuestLink(Base):
    __tablename__ = "storefront_session_guest_links"
    __table_args__ = (
        Index("ix_ssgl_session_fp", "session_fp"),
        Index("ix_ssgl_session_fp_created", "session_fp", "created_at"),
        Index("ix_ssgl_guest_id", "guest_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_fp = Column(String(64), nullable=False)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False)
    reservation_hold_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reservation_holds.id", ondelete="SET NULL"),
        nullable=True,
    )
    source = Column(String(32), nullable=False, server_default="checkout_hold")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
