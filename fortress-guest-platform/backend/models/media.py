"""Sovereign property media ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base

if TYPE_CHECKING:
    from backend.models.property import Property


PROPERTY_IMAGE_STATUS_PENDING = "pending"
PROPERTY_IMAGE_STATUS_INGESTED = "ingested"
PROPERTY_IMAGE_STATUS_FAILED = "failed"
PROPERTY_IMAGE_STATUS_VALUES: tuple[str, str, str] = (
    PROPERTY_IMAGE_STATUS_PENDING,
    PROPERTY_IMAGE_STATUS_INGESTED,
    PROPERTY_IMAGE_STATUS_FAILED,
)


class PropertyImage(Base):
    """Tracks migration of legacy property media into sovereign object storage."""

    __tablename__ = "property_images"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ingested', 'failed')",
            name="ck_property_images_status",
        ),
        UniqueConstraint("property_id", "legacy_url", name="uq_property_images_property_legacy_url"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    property_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    legacy_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    sovereign_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    alt_text: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="",
        server_default=text("''"),
    )
    is_hero: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PROPERTY_IMAGE_STATUS_PENDING,
        server_default=text(f"'{PROPERTY_IMAGE_STATUS_PENDING}'"),
        index=True,
    )

    property: Mapped[Property] = relationship("Property", back_populates="images")

    def __repr__(self) -> str:
        return f"<PropertyImage property_id={self.property_id} status={self.status}>"
