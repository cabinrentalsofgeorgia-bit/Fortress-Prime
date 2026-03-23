"""
Agentic trust governance ledger for the GREC containment perimeter.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.core.time import utc_now


def _enum_column(enum_cls: type[enum.Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class TrustDecisionStatus(str, enum.Enum):
    AUTO_APPROVED = "auto_approved"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class EscalationStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class OverrideAction(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class AgentRegistry(Base):
    """Whitelisted financial agents permitted to propose trust decisions."""

    __tablename__ = "agent_registry"
    __table_args__ = (
        CheckConstraint(
            "daily_tool_budget >= 0",
            name="ck_agent_registry_daily_tool_budget_nonnegative",
        ),
        UniqueConstraint("name", name="uq_agent_registry_name"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        index=True,
    )
    scope_boundary: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    daily_tool_budget: Mapped[int] = mapped_column(Integer, nullable=False)

    runs: Mapped[list[AgentRun]] = relationship(
        "AgentRun",
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class AgentRun(Base):
    """Immutable execution trace for each trusted swarm invocation."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_agent_status_started", "agent_id", "status", "started_at"),
        Index("ix_agent_runs_trigger_status_started", "trigger_source", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("agent_registry.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trigger_source: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        _enum_column(AgentRunStatus, "agent_run_status"),
        nullable=False,
        default=AgentRunStatus.QUEUED,
        server_default=AgentRunStatus.QUEUED.value,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[AgentRegistry] = relationship("AgentRegistry", back_populates="runs")
    decisions: Mapped[list[TrustDecision]] = relationship(
        "TrustDecision",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class TrustDecision(Base):
    """Deterministic policy result for a proposed financial action."""

    __tablename__ = "trust_decisions"
    __table_args__ = (
        CheckConstraint(
            "deterministic_score >= 0",
            name="ck_trust_decisions_deterministic_score_nonnegative",
        ),
        Index("ix_trust_decisions_run_status", "run_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    proposed_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    deterministic_score: Mapped[float] = mapped_column(Float, nullable=False)
    policy_evaluation: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    status: Mapped[TrustDecisionStatus] = mapped_column(
        _enum_column(TrustDecisionStatus, "trust_decision_status"),
        nullable=False,
        index=True,
    )

    run: Mapped[AgentRun] = relationship("AgentRun", back_populates="decisions")
    escalations: Mapped[list[Escalation]] = relationship(
        "Escalation",
        back_populates="decision",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list[TrustTransaction]] = relationship(
        "TrustTransaction",
        back_populates="decision",
    )


class Escalation(Base):
    """Human-in-the-loop queue for decisions that cannot self-execute."""

    __tablename__ = "swarm_escalations"
    __table_args__ = (
        Index("ix_swarm_escalations_status_reason", "status", "reason_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    decision_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trust_decisions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[EscalationStatus] = mapped_column(
        _enum_column(EscalationStatus, "swarm_escalation_status"),
        nullable=False,
        default=EscalationStatus.PENDING,
        server_default=EscalationStatus.PENDING.value,
        index=True,
    )

    decision: Mapped[TrustDecision] = relationship("TrustDecision", back_populates="escalations")
    overrides: Mapped[list[OperatorOverride]] = relationship(
        "OperatorOverride",
        back_populates="escalation",
        cascade="all, delete-orphan",
    )


class OperatorOverride(Base):
    """Permanent audit record for manual operator intervention."""

    __tablename__ = "operator_overrides"
    __table_args__ = (
        Index("ix_operator_overrides_operator_timestamp", "operator_email", "timestamp"),
        Index("ix_operator_overrides_escalation_timestamp", "escalation_id", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    escalation_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("swarm_escalations.id", ondelete="CASCADE"),
        nullable=False,
    )
    operator_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    override_action: Mapped[OverrideAction] = mapped_column(
        _enum_column(OverrideAction, "operator_override_action"),
        nullable=False,
    )
    final_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("now()"),
        index=True,
    )

    escalation: Mapped[Escalation] = relationship("Escalation", back_populates="overrides")

