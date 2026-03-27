"""
Treasury and SEO rank telemetry models.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Column, Date, DateTime, Enum as SqlEnum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OTAProvider(str, enum.Enum):
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    BOOKING = "booking_com"


class YieldSimulation(Base):
    __tablename__ = "yield_simulations"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PostgresUUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False)
    assumptions = Column(JSONB, nullable=False, default=dict)
    simulated_revenue = Column(Numeric(12, 2), nullable=False, default=0)
    simulated_margin = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class YieldOverride(Base):
    __tablename__ = "yield_overrides"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PostgresUUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False)
    reason = Column(String(255), nullable=False)
    override_payload = Column(JSONB, nullable=False, default=dict)
    created_by = Column(String(120), nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SeoRankSnapshot(Base):
    __tablename__ = "seo_rank_snapshots"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PostgresUUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    keyword = Column(String(255), nullable=False, index=True)
    rank_position = Column(String(30), nullable=False, default="-")
    snapshot_date = Column(Date, nullable=False, default=date.today, index=True)
    source = Column(String(120), nullable=False, default="manual")
    metadata_json = Column(JSONB, nullable=False, default=dict)


class OtaMicroUpdate(Base):
    __tablename__ = "ota_micro_updates"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PostgresUUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    channel = Column(String(80), nullable=False, index=True)
    patch_payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="queued", index=True)
    error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CompetitorListing(Base):
    """
    STRIKE 24: THE PRICE SENTINEL.
    Tracks external pricing for sovereign properties to prove Direct-Book Alpha.
    """

    __tablename__ = "competitor_listings"
    __table_args__ = (
        UniqueConstraint("dedupe_hash", name="uq_competitor_listings_dedupe_hash"),
        Index("ix_competitor_listings_property_platform_observed", "property_id", "platform", "last_observed"),
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
    platform: Mapped[OTAProvider] = mapped_column(
        SqlEnum(
            OTAProvider,
            name="ota_provider",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    observed_nightly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observed_total_before_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0"),
    )
    cleaning_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0"),
    )
    total_after_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    snapshot_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    last_observed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<CompetitorListing {self.platform.value} property={self.property_id} "
            f"nightly={self.observed_nightly_rate}>"
        )
