"""
Queue of AI-proposed redirect remaps for quarantined legacy paths.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Float, Index, String, Text, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class SeoRedirectRemapQueue(Base):
    __tablename__ = "seo_redirect_remap_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','promoted','rejected','applied','superseded')",
            name="ck_seo_redirect_remap_queue_status",
        ),
        UniqueConstraint(
            "source_path",
            "campaign",
            "proposal_run_id",
            name="uq_seo_redirect_remap_queue_source_campaign_run",
        ),
        Index("ix_seo_redirect_remap_queue_status_created", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_path = Column(String(1024), nullable=False, index=True)
    current_destination_path = Column(String(1024), nullable=True)
    proposed_destination_path = Column(String(1024), nullable=False)
    applied_destination_path = Column(String(1024), nullable=True)
    grounding_mode = Column(String(100), nullable=False, default="swarm_semantic_match")
    status = Column(String(30), nullable=False, default="proposed", index=True)

    campaign = Column(String(100), nullable=False, default="seo_fallback_swarm", index=True)
    rubric_version = Column(String(50), nullable=False, default="seo_redirect_remap_v1")
    proposal_run_id = Column(String(100), nullable=False, index=True)
    proposed_by = Column(String(100), nullable=False, default="nemoclaw_swarm")

    extracted_entities = Column(JSONB, nullable=False, default=list)
    source_snapshot = Column(JSONB, nullable=False, default=dict)
    route_candidates = Column(JSONB, nullable=False, default=list)
    rationale = Column(Text, nullable=False, default="")

    grade_score = Column(Float, nullable=True)
    grade_payload = Column(JSONB, nullable=False, default=dict)
    reviewed_by = Column(String(255), nullable=True)
    review_note = Column(Text, nullable=True)
    approved_at = Column(TIMESTAMP, nullable=True)

    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SeoRedirectRemapQueue source={self.source_path} status={self.status}>"
