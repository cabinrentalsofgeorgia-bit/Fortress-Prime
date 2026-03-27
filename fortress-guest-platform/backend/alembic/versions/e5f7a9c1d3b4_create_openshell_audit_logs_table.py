"""create openshell audit logs table

Revision ID: e5f7a9c1d3b4
Revises: d4e6f8a1b2c3
Create Date: 2026-03-22 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f7a9c1d3b4"
down_revision: Union[str, None] = "d4e6f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "openshell_audit_logs" in tables:
        return

    op.create_table(
        "openshell_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=True),
        sa.Column(
            "redaction_status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'not_applicable'"),
        ),
        sa.Column("model_route", sa.String(length=120), nullable=True),
        sa.Column(
            "outcome",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'success'"),
        ),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("prev_hash", sa.String(length=128), nullable=True),
        sa.Column("entry_hash", sa.String(length=128), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_hash", name="uq_openshell_audit_logs_entry_hash"),
    )
    op.create_index("ix_openshell_audit_logs_actor_id", "openshell_audit_logs", ["actor_id"], unique=False)
    op.create_index("ix_openshell_audit_logs_action", "openshell_audit_logs", ["action"], unique=False)
    op.create_index(
        "ix_openshell_audit_logs_resource_type",
        "openshell_audit_logs",
        ["resource_type"],
        unique=False,
    )
    op.create_index("ix_openshell_audit_logs_tool_name", "openshell_audit_logs", ["tool_name"], unique=False)
    op.create_index(
        "ix_openshell_audit_logs_redaction_status",
        "openshell_audit_logs",
        ["redaction_status"],
        unique=False,
    )
    op.create_index(
        "ix_openshell_audit_logs_model_route",
        "openshell_audit_logs",
        ["model_route"],
        unique=False,
    )
    op.create_index("ix_openshell_audit_logs_outcome", "openshell_audit_logs", ["outcome"], unique=False)
    op.create_index("ix_openshell_audit_logs_request_id", "openshell_audit_logs", ["request_id"], unique=False)
    op.create_index(
        "ix_openshell_audit_logs_payload_hash",
        "openshell_audit_logs",
        ["payload_hash"],
        unique=False,
    )
    op.create_index("ix_openshell_audit_logs_prev_hash", "openshell_audit_logs", ["prev_hash"], unique=False)
    op.create_index("ix_openshell_audit_logs_entry_hash", "openshell_audit_logs", ["entry_hash"], unique=False)
    op.create_index("ix_openshell_audit_logs_created_at", "openshell_audit_logs", ["created_at"], unique=False)
    bind.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE openshell_audit_logs TO fortress_api"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "openshell_audit_logs" not in tables:
        return

    op.drop_index("ix_openshell_audit_logs_created_at", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_entry_hash", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_prev_hash", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_payload_hash", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_request_id", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_outcome", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_model_route", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_redaction_status", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_tool_name", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_resource_type", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_action", table_name="openshell_audit_logs")
    op.drop_index("ix_openshell_audit_logs_actor_id", table_name="openshell_audit_logs")
    op.drop_table("openshell_audit_logs")
