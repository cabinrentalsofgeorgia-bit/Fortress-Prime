"""
Explicit Rue Ba Rue legacy recovery SMS templates for parity vs sovereign drafts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RueBaRueLegacyRecoveryTemplate(Base):
    """Catalog row for generic time-delayed legacy recovery copy (Rue Ba Rue baseline)."""

    __tablename__ = "rue_bar_rue_legacy_recovery_templates"
    __table_args__ = (UniqueConstraint("template_key", name="uq_rbr_legacy_recovery_template_key"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    template_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    audience_rule: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="*",
        server_default="*",
        index=True,
        doc="Funnel drop-off stage match, or '*' for default.",
    )
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    source_system: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="rue_ba_rue",
        server_default="rue_ba_rue",
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
