"""
Phase 2 legal models — CaseStatement, SanctionsAlert,
JurisdictionRule, HiveMindFeedbackEvent.

All tables live under the ``legal`` schema via LegalBase.
Models match the existing hand-created table schemas.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.models.legal_base import LegalBase


class CaseStatement(LegalBase):
    __tablename__ = "case_statements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_slug = Column(String(255), nullable=False, index=True)
    entity_name = Column(Text, nullable=False, index=True)
    quote_text = Column(Text, nullable=False)
    source_ref = Column(Text, nullable=True)
    doc_id = Column(Text, nullable=True)
    stated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SanctionsAlert(LegalBase):
    __tablename__ = "sanctions_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_slug = Column(String(255), nullable=False, index=True)
    alert_type = Column(String(32), nullable=False)  # rule11 | spoliation
    filing_ref = Column(Text, nullable=True)
    contradiction_summary = Column(Text, nullable=True)
    draft_content_ref = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class JurisdictionRule(LegalBase):
    __tablename__ = "jurisdiction_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    court_name = Column(String(255), nullable=False, index=True)
    rule_type = Column(String(64), nullable=False)
    limit_value = Column(Integer, nullable=False)
    source_ref = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class HiveMindFeedbackEvent(LegalBase):
    __tablename__ = "hive_mind_feedback_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    pack_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal.discovery_draft_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feedback_type = Column(String(32), nullable=False)  # approve | reject | edit
    original_content = Column(Text, nullable=True)
    revised_content = Column(Text, nullable=True)
    quality_score = Column(Float, nullable=True)
    event_metadata = Column("metadata", JSONB, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PrivilegeLog(LegalBase):
    __tablename__ = "privilege_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    case_slug = Column(String(255), nullable=False, index=True)
    file_name = Column(String(500), nullable=False)
    privilege_type = Column(String(64), nullable=False)
    reasoning = Column(Text, nullable=False)
    model_used = Column(String(128), nullable=False)
    latency_ms = Column(Integer, nullable=False, default=0)
    classifier_confidence = Column(Float, nullable=True)
    snippet = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AiAuditLedger(LegalBase):
    __tablename__ = "ai_audit_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_slug = Column(String(255), nullable=True, index=True)
    action_type = Column(String(128), nullable=False)
    model_used = Column(String(128), nullable=False)
    source = Column(String(64), nullable=False, default="local_dgx")
    prompt_hash = Column(String(64), nullable=False, index=True)
    prompt_text = Column(Text, nullable=True)
    retrieved_vectors = Column(JSONB, nullable=True, default=list)
    raw_output = Column(Text, nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="success")
    source_module = Column(String(128), nullable=True)
    task_type = Column(String(64), nullable=True)
    breaker_state = Column(String(32), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
