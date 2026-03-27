"""
Persistent background job ledger for ARQ-dispatched work.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AsyncJobRun(Base):
    """Tracks queue lifecycle for fire-and-forget jobs initiated by the API."""

    __tablename__ = "async_job_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_async_job_runs_status",
        ),
        Index("ix_async_job_runs_job_status_created", "job_name", "status", "created_at"),
        Index("ix_async_job_runs_status_created", "status", "created_at"),
        Index("ix_async_job_runs_requested_by_created", "requested_by", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_name = Column(String(100), nullable=False, index=True)
    queue_name = Column(String(100), nullable=False, default="fortress:arq", index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)

    requested_by = Column(String(255), nullable=True, index=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)

    arq_job_id = Column(String(100), nullable=True, unique=True, index=True)
    attempts = Column(Integer, nullable=False, default=0)

    payload_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<AsyncJobRun {self.job_name} status={self.status}>"
