"""
Intelligence ledger models for sovereign market discoveries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntelligenceLedgerEntry(Base):
    """Immutable ledger row for each unique Scout finding."""

    __tablename__ = "intelligence_ledger"
    __table_args__ = (
        UniqueConstraint("dedupe_hash", name="uq_intelligence_ledger_dedupe_hash"),
        Index("ix_intelligence_ledger_category_discovered", "category", "discovered_at"),
        Index("ix_intelligence_ledger_market_discovered", "market", "discovered_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    locality: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    query_topic: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    scout_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    scout_run_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    target_property_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    target_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    grounding_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    finding_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
