"""create ai_insights table for event-consumer NemoClaw persistence

Revision ID: c7d8e9f0a1b2
Revises: a9c1e4f8b2d0
Create Date: 2026-03-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "a9c1e4f8b2d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("reference_id", sa.String(length=255), nullable=False),
        sa.Column(
            "insight_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_ai_insights_task_id"),
    )
    op.create_index("ix_ai_insights_event_type", "ai_insights", ["event_type"], unique=False)
    op.create_index("ix_ai_insights_reference_id", "ai_insights", ["reference_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_insights_reference_id", table_name="ai_insights")
    op.drop_index("ix_ai_insights_event_type", table_name="ai_insights")
    op.drop_table("ai_insights")
