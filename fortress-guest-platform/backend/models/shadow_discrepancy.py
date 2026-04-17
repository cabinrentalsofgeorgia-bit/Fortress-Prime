"""Shadow Ledger — tracks pricing discrepancies between Legacy and DGX."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class ShadowDiscrepancy(Base):
    __tablename__ = "shadow_discrepancies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    property_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    legacy_total_cents = Column(Integer, nullable=False)
    dgx_total_cents = Column(Integer, nullable=False)
    delta_cents = Column(Integer, nullable=False)
    legacy_payload = Column(JSONB, nullable=True)
    dgx_payload = Column(JSONB, nullable=True)
    hermes_diagnosis = Column(Text, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
