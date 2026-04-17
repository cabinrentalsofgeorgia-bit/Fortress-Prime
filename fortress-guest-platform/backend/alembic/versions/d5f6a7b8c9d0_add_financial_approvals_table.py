"""Add financial_approvals table for sovereign AI queue.

Revision ID: d5f6a7b8c9d0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-03
"""

revision = "d5f6a7b8c9d0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade() -> None:
    op.create_table(
        "financial_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", sa.String(100), nullable=False, index=True),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("discrepancy_type", sa.String(100), nullable=False),
        sa.Column("local_total_cents", sa.Integer, nullable=False),
        sa.Column("streamline_total_cents", sa.Integer, nullable=False),
        sa.Column("delta_cents", sa.Integer, nullable=False),
        sa.Column("context_payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("financial_approvals")
