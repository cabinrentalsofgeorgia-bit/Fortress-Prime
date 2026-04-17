"""Taylor multi-property availability-first quote request model."""
from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class TaylorQuoteStatus(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"
    SENT = "sent"
    EXPIRED = "expired"


class TaylorQuoteRequest(Base):
    """
    Multi-property quote request awaiting Taylor's one-click approval.

    On creation, ``property_options`` holds every available property with live
    Streamline pricing for the requested dates.  Taylor reviews the list in the
    Command Center and clicks Approve — the system sends a rich HTML email to
    the guest and marks this record as sent.
    """

    __tablename__ = "taylor_quote_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    guest_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    adults: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    children: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pets: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # "pending_approval" | "sent" | "expired"
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=TaylorQuoteStatus.PENDING_APPROVAL.value,
        server_default=text("'pending_approval'"),
        index=True,
    )
    # Each element: {property_id, property_name, slug, bedrooms, bathrooms,
    # max_guests, hero_image_url, base_rent, taxes, fees, total_amount,
    # nights, pricing_source, booking_url}
    property_options: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    approved_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
