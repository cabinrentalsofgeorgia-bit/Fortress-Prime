"""Add security_deposit_payment_method_id to reservations.

Revision ID: h1a2b3c4d5e6
Revises: f9e8d7c6b5a4
Create Date: 2026-04-11
"""

from __future__ import annotations

revision = "h1a2b3c4d5e6"
down_revision = "f9e8d7c6b5a4"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("security_deposit_payment_method_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "security_deposit_payment_method_id")
