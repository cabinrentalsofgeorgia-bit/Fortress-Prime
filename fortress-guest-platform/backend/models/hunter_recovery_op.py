"""
Hunter recovery operations staged for manual revenue recovery approval.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HunterRecoveryOpStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    DRAFT_READY = "DRAFT_READY"
    DISPATCHED = "DISPATCHED"
    REJECTED = "REJECTED"


class HunterRecoveryOp(Base):
    __tablename__ = "hunter_recovery_ops"
    __table_args__ = (
        Index("ix_hunter_recovery_ops_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    cart_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    guest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cabin_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cart_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[HunterRecoveryOpStatus] = mapped_column(
        Enum(HunterRecoveryOpStatus, name="hunter_recovery_op_status"),
        nullable=False,
        default=HunterRecoveryOpStatus.QUEUED,
        server_default=HunterRecoveryOpStatus.QUEUED.value,
        index=True,
    )
    ai_draft_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_worker: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
