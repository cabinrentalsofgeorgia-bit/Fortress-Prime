"""
Queued outbound API writes when Streamline circuit is open or Strike 20 enqueues replay.

Replayed by :class:`~backend.services.reconciliation_janitor.ReconciliationJanitor`.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import synonym

from backend.core.database import Base


class DeferredWriteStatus(StrEnum):
    """Persisted in ``deferred_api_writes.status`` (lowercase strings)."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED_FINAL = "failed_final"


class DeferredApiWrite(Base):
    __tablename__ = "deferred_api_writes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    service = Column(String(128), nullable=False, index=True)
    method = Column(String(512), nullable=False)
    method_name = synonym("method")
    payload = Column(JSONB(astext_type=Text()), nullable=False)
    status = Column(
        String(64),
        nullable=False,
        server_default=DeferredWriteStatus.PENDING.value,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    retry_count = Column(Integer, nullable=False, server_default="0")
    last_error = Column(Text, nullable=True)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<DeferredApiWrite id={self.id} service={self.service!r} status={self.status!r}>"
