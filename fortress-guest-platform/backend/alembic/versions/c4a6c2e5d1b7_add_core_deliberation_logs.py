"""Add core.deliberation_logs for Division 1 Concierge verdicts.

Revision ID: c4a6c2e5d1b7
Revises: 8029df49b834
Create Date: 2026-03-29 15:56:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4a6c2e5d1b7"
down_revision: Union[str, Sequence[str], None] = "8029df49b834"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.create_table(
        "deliberation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict_type", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_verdict_type",
        "deliberation_logs",
        ["verdict_type"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_session_id",
        "deliberation_logs",
        ["session_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_guest_id",
        "deliberation_logs",
        ["guest_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_reservation_id",
        "deliberation_logs",
        ["reservation_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_property_id",
        "deliberation_logs",
        ["property_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_message_id",
        "deliberation_logs",
        ["message_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_deliberation_logs_created_at",
        "deliberation_logs",
        ["created_at"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("ix_core_deliberation_logs_created_at", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_message_id", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_property_id", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_reservation_id", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_guest_id", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_session_id", table_name="deliberation_logs", schema="core")
    op.drop_index("ix_core_deliberation_logs_verdict_type", table_name="deliberation_logs", schema="core")
    op.drop_table("deliberation_logs", schema="core")
