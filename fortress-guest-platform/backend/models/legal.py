"""
Legal ontology models for Step 1.1 (epistemological base).
All tables are additive and isolated under the legal schema.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


class LegalEntity(Base):
    __tablename__ = "entities"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, index=True)
    type = Column(String(100), nullable=False, index=True)
    role = Column(String(100), nullable=True)


class CaseEvidence(Base):
    __tablename__ = "case_evidence"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_name = Column(String(500), nullable=False)
    nas_path = Column(Text, nullable=False)
    qdrant_point_id = Column(String(255), nullable=True, index=True)
    sha256_hash = Column(String(128), nullable=False, index=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=False)
    source_evidence_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_evidence.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class DistillationMemory(Base):
    __tablename__ = "distillation_memory"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    context_hash = Column(String(128), nullable=False, unique=True, index=True)
    frontier_insight = Column(Text, nullable=False)
    local_correction = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CaseGraphNode(Base):
    __tablename__ = "case_graph_nodes_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)  # person|document|claim|company
    entity_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    label = Column(String(500), nullable=False)
    properties_json = Column(JSONB, nullable=False, default=dict)


class CaseGraphEdge(Base):
    __tablename__ = "case_graph_edges_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    source_node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_graph_nodes_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.case_graph_nodes_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type = Column(String(128), nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    source_evidence_id = Column(UUID(as_uuid=True), nullable=True, index=True)


class DiscoveryDraftPack(Base):
    __tablename__ = "discovery_draft_packs_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    target_entity = Column(String(255), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="DRAFT", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class DiscoveryDraftItem(Base):
    __tablename__ = "discovery_draft_items_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    pack_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.discovery_draft_packs_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=False)
    rationale_from_graph = Column(Text, nullable=False)
    sequence_number = Column(Integer, nullable=False)
    lethality_score = Column(Integer, nullable=True)
    proportionality_score = Column(Integer, nullable=True)
    correction_notes = Column(String(2000), nullable=True)


class SanctionsAlert(Base):
    __tablename__ = "sanctions_alerts_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    alert_type = Column(String(32), nullable=False, index=True)  # RULE_11 | SPOLIATION
    contradiction_summary = Column(Text, nullable=False)
    confidence_score = Column(Integer, nullable=False, default=50, index=True)
    status = Column(String(32), nullable=False, default="DRAFT", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SanctionsTripwireRun(Base):
    __tablename__ = "sanctions_tripwire_runs_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    trigger_source = Column(String(64), nullable=False, default="cron", index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    model_used = Column(String(128), nullable=True)
    alerts_found = Column(Integer, nullable=False, default=0)
    alerts_saved = Column(Integer, nullable=False, default=0)
    error_detail = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CaseStatement(Base):
    __tablename__ = "case_statements_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    quote_text = Column(Text, nullable=False)
    source_ref = Column(Text, nullable=True)
    doc_id = Column(String(255), nullable=True, index=True)
    stated_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class DepositionKillSheet(Base):
    __tablename__ = "deposition_kill_sheets_v2"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=False, index=True)
    deponent_entity = Column(String(255), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="DRAFT", index=True)
    summary = Column(Text, nullable=False)
    high_risk_topics_json = Column(JSONB, nullable=False, default=list)
    document_sequence_json = Column(JSONB, nullable=False, default=list)
    suggested_questions_json = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LegalExemplar(Base):
    __tablename__ = "legal_exemplars"
    __table_args__ = {"schema": "legal"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    category = Column(String(32), nullable=False, index=True)
    rationale_context = Column(Text, nullable=False)
    perfect_output = Column(Text, nullable=False)
    source_model = Column(String(128), nullable=False, default="claude-3-5-sonnet")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

