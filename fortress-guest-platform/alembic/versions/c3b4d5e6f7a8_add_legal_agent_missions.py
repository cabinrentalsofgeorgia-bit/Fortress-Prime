"""add legal_agent_missions table

Revision ID: c3b4d5e6f7a8
Revises: b2a3c4d5e6f7
Create Date: 2026-03-14 06:40:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3b4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "b2a3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema="legal"))

    if "agent_missions" not in tables:
        op.execute("SET search_path TO legal, public")
        op.create_table(
            "agent_missions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("case_slug", sa.String(255), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("reasoning_log", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("final_output", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="running"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            schema="legal",
        )
        op.create_index("ix_agent_missions_case_slug", "agent_missions", ["case_slug"], schema="legal")
        op.create_index("ix_agent_missions_status", "agent_missions", ["status"], schema="legal")


def downgrade() -> None:
    op.drop_index("ix_agent_missions_status", table_name="agent_missions", schema="legal")
    op.drop_index("ix_agent_missions_case_slug", table_name="agent_missions", schema="legal")
    op.drop_table("agent_missions", schema="legal")
