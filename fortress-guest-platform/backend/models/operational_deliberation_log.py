"""
Operational deliberation ledger for Division 1 storefront verdicts.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class OperationalDeliberationLog(Base):
    """Best-effort immutable-style audit trail for Concierge conflict and triage verdicts."""

    __tablename__ = "deliberation_logs"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    verdict_type = Column(String(64), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    guest_id = Column(UUID(as_uuid=True), index=True)
    reservation_id = Column(UUID(as_uuid=True), index=True)
    property_id = Column(UUID(as_uuid=True), index=True)
    message_id = Column(UUID(as_uuid=True), index=True)
    payload_json = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<OperationalDeliberationLog verdict={self.verdict_type!r} "
            f"session={self.session_id!r}>"
        )
