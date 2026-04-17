"""Add resolution_strategy and stripe_invoice_id to financial_approvals.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-03
"""

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "financial_approvals",
        sa.Column("resolution_strategy", sa.String(30), nullable=True),
    )
    op.add_column(
        "financial_approvals",
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_financial_approvals_resolution_strategy",
        "financial_approvals",
        ["resolution_strategy"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_approvals_resolution_strategy",
        table_name="financial_approvals",
    )
    op.drop_column("financial_approvals", "stripe_invoice_id")
    op.drop_column("financial_approvals", "resolution_strategy")
