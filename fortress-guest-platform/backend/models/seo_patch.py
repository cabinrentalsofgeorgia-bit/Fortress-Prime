"""
SEO patch queue model for DGX swarm proposal/review workflow.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Index, String, Text, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class SeoPatchQueue(Base):
    """Pending and approved SEO payloads for property pages."""

    __tablename__ = "seo_patch_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','needs_revision','approved','rejected','deployed','superseded')",
            name="ck_seo_patch_queue_status",
        ),
        UniqueConstraint(
            "property_id",
            "campaign",
            "source_hash",
            name="uq_seo_patch_queue_property_campaign_source",
        ),
        Index("ix_seo_patch_queue_status_created", "status", "created_at"),
        Index("ix_seo_patch_queue_property_approved", "property_id", "approved_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
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
        return f"<SeoPatchQueue property={self.property_id} status={self.status}>"
