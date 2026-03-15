"""
Deposition planning models for graph-driven cross-examination funnels.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.models.legal_base import LegalBase


class DepositionTarget(LegalBase):
    __tablename__ = "deposition_targets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.legal_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_name = Column(String(255), nullable=False, index=True)
    role = Column(String(128), nullable=False)
    status = Column(
        Enum(
            "drafting",
            "ready",
            "completed",
            name="deposition_target_status",
            schema="legal",
        ),
        nullable=False,
        default="drafting",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class CrossExamFunnel(LegalBase):
    __tablename__ = "cross_exam_funnels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    target_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.deposition_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contradiction_edge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_graph_edges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic = Column(String(500), nullable=False)
    lock_in_questions = Column(JSONB, nullable=False, default=list)
    the_strike_document = Column(String(1000), nullable=False)
    strike_script = Column(String(4000), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
