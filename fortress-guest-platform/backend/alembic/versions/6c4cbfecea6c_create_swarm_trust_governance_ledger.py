"""create swarm trust governance ledger

Revision ID: 6c4cbfecea6c
Revises: ef4d662c7ad7
Create Date: 2026-03-22 17:04:07.861492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6c4cbfecea6c"
down_revision: Union[str, Sequence[str], None] = "ef4d662c7ad7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("scope_boundary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("daily_tool_budget", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "daily_tool_budget >= 0",
            name="ck_agent_registry_daily_tool_budget_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_agent_registry_name"),
    )
    op.create_index(op.f("ix_agent_registry_name"), "agent_registry", ["name"], unique=False)
    op.create_index(op.f("ix_agent_registry_role"), "agent_registry", ["role"], unique=False)

    op.create_table(
        "trust_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "asset",
                "liability",
                name="trust_account_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_trust_accounts_name"),
    )
    op.create_index(op.f("ix_trust_accounts_name"), "trust_accounts", ["name"], unique=False)
    op.create_index(op.f("ix_trust_accounts_type"), "trust_accounts", ["type"], unique=False)
    op.create_index("ix_trust_accounts_type_name", "trust_accounts", ["type", "name"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_source", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "failed",
                "escalated",
                "blocked",
                name="agent_run_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_registry.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_agent_status_started", "agent_runs", ["agent_id", "status", "started_at"], unique=False)
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)
    op.create_index(op.f("ix_agent_runs_trigger_source"), "agent_runs", ["trigger_source"], unique=False)
    op.create_index(
        "ix_agent_runs_trigger_status_started",
        "agent_runs",
        ["trigger_source", "status", "started_at"],
        unique=False,
    )

    op.create_table(
        "trust_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deterministic_score", sa.Float(), nullable=False),
        sa.Column("policy_evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "auto_approved",
                "escalated",
                "blocked",
                name="trust_decision_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "deterministic_score >= 0",
            name="ck_trust_decisions_deterministic_score_nonnegative",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trust_decisions_run_status", "trust_decisions", ["run_id", "status"], unique=False)
    op.create_index(op.f("ix_trust_decisions_status"), "trust_decisions", ["status"], unique=False)

    op.create_table(
        "swarm_escalations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "resolved",
                name="swarm_escalation_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["trust_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index(op.f("ix_swarm_escalations_reason_code"), "swarm_escalations", ["reason_code"], unique=False)
    op.create_index(op.f("ix_swarm_escalations_status"), "swarm_escalations", ["status"], unique=False)
    op.create_index(
        "ix_swarm_escalations_status_reason",
        "swarm_escalations",
        ["status", "reason_code"],
        unique=False,
    )

    op.create_table(
        "trust_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("streamline_event_id", sa.String(length=255), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["trust_decisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trust_transactions_decision_timestamp",
        "trust_transactions",
        ["decision_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_transactions_streamline_event_id"),
        "trust_transactions",
        ["streamline_event_id"],
        unique=False,
    )
    op.create_index(op.f("ix_trust_transactions_timestamp"), "trust_transactions", ["timestamp"], unique=False)

    op.create_table(
        "operator_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("escalation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_email", sa.String(length=255), nullable=False),
        sa.Column(
            "override_action",
            sa.Enum(
                "approve",
                "reject",
                "modify",
                name="operator_override_action",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("final_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["escalation_id"], ["swarm_escalations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operator_overrides_escalation_timestamp",
        "operator_overrides",
        ["escalation_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operator_overrides_operator_email"),
        "operator_overrides",
        ["operator_email"],
        unique=False,
    )
    op.create_index(
        "ix_operator_overrides_operator_timestamp",
        "operator_overrides",
        ["operator_email", "timestamp"],
        unique=False,
    )
    op.create_index(op.f("ix_operator_overrides_timestamp"), "operator_overrides", ["timestamp"], unique=False)

    op.create_table(
        "trust_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "debit",
                "credit",
                name="trust_ledger_entry_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_cents > 0",
            name="ck_trust_ledger_entries_amount_positive",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["trust_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["trust_transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trust_ledger_entries_account_id"), "trust_ledger_entries", ["account_id"], unique=False)
    op.create_index(op.f("ix_trust_ledger_entries_entry_type"), "trust_ledger_entries", ["entry_type"], unique=False)
    op.create_index(
        op.f("ix_trust_ledger_entries_transaction_id"),
        "trust_ledger_entries",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_trust_ledger_entries_transaction_id"), table_name="trust_ledger_entries")
    op.drop_index(op.f("ix_trust_ledger_entries_entry_type"), table_name="trust_ledger_entries")
    op.drop_index(op.f("ix_trust_ledger_entries_account_id"), table_name="trust_ledger_entries")
    op.drop_table("trust_ledger_entries")

    op.drop_index(op.f("ix_operator_overrides_timestamp"), table_name="operator_overrides")
    op.drop_index("ix_operator_overrides_operator_timestamp", table_name="operator_overrides")
    op.drop_index(op.f("ix_operator_overrides_operator_email"), table_name="operator_overrides")
    op.drop_index("ix_operator_overrides_escalation_timestamp", table_name="operator_overrides")
    op.drop_table("operator_overrides")

    op.drop_index(op.f("ix_trust_transactions_timestamp"), table_name="trust_transactions")
    op.drop_index(op.f("ix_trust_transactions_streamline_event_id"), table_name="trust_transactions")
    op.drop_index("ix_trust_transactions_decision_timestamp", table_name="trust_transactions")
    op.drop_table("trust_transactions")

    op.drop_index("ix_swarm_escalations_status_reason", table_name="swarm_escalations")
    op.drop_index(op.f("ix_swarm_escalations_status"), table_name="swarm_escalations")
    op.drop_index(op.f("ix_swarm_escalations_reason_code"), table_name="swarm_escalations")
    op.drop_table("swarm_escalations")

    op.drop_index(op.f("ix_trust_decisions_status"), table_name="trust_decisions")
    op.drop_index("ix_trust_decisions_run_status", table_name="trust_decisions")
    op.drop_table("trust_decisions")

    op.drop_index("ix_agent_runs_trigger_status_started", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_trigger_source"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_status_started", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_trust_accounts_type_name", table_name="trust_accounts")
    op.drop_index(op.f("ix_trust_accounts_type"), table_name="trust_accounts")
    op.drop_index(op.f("ix_trust_accounts_name"), table_name="trust_accounts")
    op.drop_table("trust_accounts")

    op.drop_index(op.f("ix_agent_registry_role"), table_name="agent_registry")
    op.drop_index(op.f("ix_agent_registry_name"), table_name="agent_registry")
    op.drop_table("agent_registry")
