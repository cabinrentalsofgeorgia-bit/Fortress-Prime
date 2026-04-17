"""
ParityAudit — Records of parity checks between local ledger and Streamline totals.

After Hermes syncs a reservation to Streamline and obtains a confirmation_id,
the system calls GetReservationPrice and compares Streamline's total against
the local ledger. Results are persisted here for audit trail and alerting.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Column, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class ParityAudit(Base):
    __tablename__ = "parity_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    confirmation_id = Column(String(100), nullable=False, index=True)
    local_total = Column(Numeric(12, 2), nullable=False)
    streamline_total = Column(Numeric(12, 2), nullable=False)
    delta = Column(Numeric(12, 2), nullable=False)
    local_breakdown = Column(JSONB, nullable=False, server_default="{}")
    streamline_breakdown = Column(JSONB, nullable=False, server_default="{}")
    status = Column(String(30), nullable=False, index=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
