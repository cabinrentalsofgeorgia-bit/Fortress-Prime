"""Make trust_transactions.decision_id nullable for system-initiated entries.

Revision ID: e6f7a8b9c0d1
Revises: d5f6a7b8c9d0
Create Date: 2026-04-03
"""

revision = "e6f7a8b9c0d1"
down_revision = "d5f6a7b8c9d0"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column(
        "trust_transactions",
        "decision_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM trust_transactions WHERE decision_id IS NULL"
    )
    op.alter_column(
        "trust_transactions",
        "decision_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
