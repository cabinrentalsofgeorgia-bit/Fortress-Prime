"""
Legal case graph models (isolated under legal schema).
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import synonym

from backend.models.legal_base import LegalBase


class LegalCase(LegalBase):
    __tablename__ = "legal_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    case_slug = synonym("slug")
    court = Column(String(255), nullable=False)
    jurisdiction = Column(String(255), nullable=False)
    status = Column(String(64), nullable=False, default="open")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class CaseGraphNode(LegalBase):
    __tablename__ = "case_graph_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.legal_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type = Column(String(64), nullable=False)  # person|company|document|claim
    label = Column(String(500), nullable=False)
    node_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class CaseGraphEdge(LegalBase):
    __tablename__ = "case_graph_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.legal_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type = Column(String(128), nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    source_ref = Column(String(500), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
