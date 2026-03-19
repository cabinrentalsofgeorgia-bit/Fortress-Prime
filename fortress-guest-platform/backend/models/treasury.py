"""
Treasury and SEO rank telemetry models.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class YieldSimulation(Base):
    __tablename__ = "yield_simulations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False)
    assumptions = Column(JSONB, nullable=False, default=dict)
    simulated_revenue = Column(Numeric(12, 2), nullable=False, default=0)
    simulated_margin = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class YieldOverride(Base):
    __tablename__ = "yield_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False)
    reason = Column(String(255), nullable=False)
    override_payload = Column(JSONB, nullable=False, default=dict)
    created_by = Column(String(120), nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SeoRankSnapshot(Base):
    __tablename__ = "seo_rank_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    keyword = Column(String(255), nullable=False, index=True)
    rank_position = Column(String(30), nullable=False, default="-")
    snapshot_date = Column(Date, nullable=False, default=date.today, index=True)
    source = Column(String(120), nullable=False, default="manual")
    metadata_json = Column(JSONB, nullable=False, default=dict)


class OtaMicroUpdate(Base):
    __tablename__ = "ota_micro_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    channel = Column(String(80), nullable=False, index=True)
    patch_payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="queued", index=True)
    error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
