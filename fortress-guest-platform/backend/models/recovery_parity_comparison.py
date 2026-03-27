"""
Persisted legacy vs sovereign recovery draft parity rows (Strike 16.4).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecoveryParityComparison(Base):
    __tablename__ = "recovery_parity_comparisons"
    __table_args__ = (
        UniqueConstraint("dedupe_hash", name="uq_recovery_parity_comparisons_dedupe_hash"),
        Index("ix_recovery_parity_session_fp_created", "session_fp", "created_at"),
        Index("ix_recovery_parity_guest_created", "guest_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_fp: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    guest_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    property_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drop_off_point: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_score_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    legacy_template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    legacy_body: Mapped[str] = mapped_column(Text, nullable=False)
    sovereign_body: Mapped[str] = mapped_column(Text, nullable=False)
    parity_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    candidate_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    async_job_run_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("now()"),
        index=True,
    )
