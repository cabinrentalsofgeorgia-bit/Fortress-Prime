"""
SEO patch queue model for DGX swarm proposal/review workflow.

Includes:
- SeoPatchQueue: Legacy polymorphic patch queue (property + archive_review)
- SEORubric: God Head grading rubrics per keyword cluster
- SEOPatch: Strictly typed swarm-generated SEO proposals with HITL workflow
"""
import uuid
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Index, Integer,
    String, Text, DateTime, TIMESTAMP, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.core.database import Base


class SeoPatchQueue(Base):
    """Pending and approved SEO payloads for property and archive pages."""

    __tablename__ = "seo_patch_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','needs_revision','approved','rejected','deployed','superseded')",
            name="ck_seo_patch_queue_status",
        ),
        CheckConstraint(
            "target_type IN ('property','archive_review')",
            name="ck_seo_patch_queue_target_type",
        ),
        UniqueConstraint(
            "target_type",
            "target_slug",
            "campaign",
            "source_hash",
            name="uq_seo_patch_queue_target_campaign_source",
        ),
        Index("ix_seo_patch_queue_status_created", "status", "created_at"),
        Index("ix_seo_patch_queue_target_approved", "target_type", "target_slug", "approved_at"),
        Index("ix_seo_patch_queue_property_approved", "property_id", "approved_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    target_type = Column(String(32), nullable=False, default="property", index=True)
    target_slug = Column(String(255), nullable=False, index=True)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status = Column(String(30), nullable=False, default="proposed", index=True)

    target_keyword = Column(String(255))
    campaign = Column(String(100), nullable=False, default="default", index=True)
    rubric_version = Column(String(50))
    source_hash = Column(String(128), nullable=False)

    proposed_title = Column(String(255), nullable=False, default="")
    proposed_meta_description = Column(Text, nullable=False, default="")
    proposed_h1 = Column(String(255), nullable=False, default="")
    proposed_intro = Column(Text, nullable=False, default="")
    proposed_faq = Column(JSONB, nullable=False, default=list)
    proposed_json_ld = Column(JSONB, nullable=False, default=dict)

    fact_snapshot = Column(JSONB, nullable=False, default=dict)

    score_overall = Column(Float)
    score_breakdown = Column(JSONB, nullable=False, default=dict)

    proposed_by = Column(String(100), nullable=False, default="dgx-swarm")
    proposal_run_id = Column(String(100))

    reviewed_by = Column(String(100))
    review_note = Column(Text)
    approved_payload = Column(JSONB, nullable=False, default=dict)
    approved_at = Column(TIMESTAMP)
    deployed_at = Column(TIMESTAMP)

    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    prop = relationship("Property")

    def __repr__(self) -> str:
        return f"<SeoPatchQueue target={self.target_type}:{self.target_slug} status={self.status}>"


# ---------------------------------------------------------------------------
# God Head Rubric + Swarm Patch models (SQLAlchemy 2.0 typed)
# ---------------------------------------------------------------------------

class SEORubric(Base):
    """Grading rubric used by the God Head evaluator per keyword cluster."""

    __tablename__ = "seo_rubrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keyword_cluster: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_model: Mapped[str] = mapped_column(String, nullable=False)
    min_pass_score: Mapped[float] = mapped_column(Float, default=0.95, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patches: Mapped[list["SEOPatch"]] = relationship("SEOPatch", back_populates="rubric", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SEORubric cluster={self.keyword_cluster!r} status={self.status}>"


class SEOPatch(Base):
    """Strictly typed swarm-generated SEO proposal with God Head grading and HITL workflow."""

    __tablename__ = "seo_patches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id"), nullable=True, index=True)
    rubric_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("seo_rubrics.id"), nullable=True)
    page_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    patch_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Proposed SEO payload
    title: Mapped[Optional[str]] = mapped_column(String(70))
    meta_description: Mapped[Optional[str]] = mapped_column(String(320))
    og_title: Mapped[Optional[str]] = mapped_column(String(95))
    og_description: Mapped[Optional[str]] = mapped_column(String(200))
    jsonld_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    canonical_url: Mapped[Optional[str]] = mapped_column(String)
    h1_suggestion: Mapped[Optional[str]] = mapped_column(String)
    alt_tags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    # God Head feedback
    godhead_score: Mapped[Optional[float]] = mapped_column(Float)
    godhead_model: Mapped[Optional[str]] = mapped_column(String)
    godhead_feedback: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    grade_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # HITL workflow & state
    status: Mapped[str] = mapped_column(String, default="drafted", nullable=False, index=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    final_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)

    # Swarm telemetry
    swarm_model: Mapped[Optional[str]] = mapped_column(String)
    swarm_node: Mapped[Optional[str]] = mapped_column(String)
    generation_ms: Mapped[Optional[int]] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rubric: Mapped[Optional["SEORubric"]] = relationship("SEORubric", back_populates="patches")

    def __repr__(self) -> str:
        return f"<SEOPatch path={self.page_path!r} status={self.status} score={self.godhead_score}>"
