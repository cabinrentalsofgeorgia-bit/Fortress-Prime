"""
Discovery draft pack/item models for legal workflow.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from backend.models.legal_base import LegalBase


class DiscoveryDraftPack(LegalBase):
    __tablename__ = "discovery_draft_packs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.legal_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pack_type = Column(String(32), nullable=False)  # interrogatory|rfp|admission
    status = Column(String(32), nullable=False, default="draft")  # draft|counsel_review|approved|rejected
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class DiscoveryDraftItem(LegalBase):
    __tablename__ = "discovery_draft_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    pack_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.discovery_draft_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    relevance_score = Column(Float, nullable=False, default=0.0)
    proportionality_flag = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
