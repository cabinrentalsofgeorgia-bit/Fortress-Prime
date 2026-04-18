"""G.6: add owner_middle_name to owner_payout_accounts

Stores the owner's middle name from Streamline's GetOwnerInfo response.
Used for name rendering in Streamline's last-middle-first format
(e.g., "Knight Mitchell Gary") on owner statement PDFs.

Revision ID: g6a1_add_owner_middle_name
Revises: e6a1b2c3d4f5
Create Date: 2026-04-15
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "g6a1_add_owner_middle_name"
down_revision = "e6a1b2c3d4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "owner_payout_accounts",
        sa.Column("owner_middle_name", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("owner_payout_accounts", "owner_middle_name")
