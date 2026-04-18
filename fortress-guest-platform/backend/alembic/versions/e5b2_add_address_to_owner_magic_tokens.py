"""Phase E.5 — add mailing address columns to owner_magic_tokens.

Invite creation now captures the owner's mailing address up front
and copies it to owner_payout_accounts when accept_invite() runs,
following the same pattern as commission_rate from Phase 1.5.

Revision ID: e5b2c3d4e5f6
Revises: e5a1b2c3d4f5
Create Date: 2026-04-14
"""
from __future__ import annotations

revision = "e5b2c3d4e5f6"
down_revision = "e5a1b2c3d4f5"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "owner_magic_tokens",
        sa.Column("mailing_address_line1", sa.String(255), nullable=True),
    )
    op.add_column(
        "owner_magic_tokens",
        sa.Column("mailing_address_line2", sa.String(255), nullable=True),
    )
    op.add_column(
        "owner_magic_tokens",
        sa.Column("mailing_address_city", sa.String(100), nullable=True),
    )
    op.add_column(
        "owner_magic_tokens",
        sa.Column("mailing_address_state", sa.String(50), nullable=True),
    )
    op.add_column(
        "owner_magic_tokens",
        sa.Column("mailing_address_postal_code", sa.String(20), nullable=True),
    )
    op.add_column(
        "owner_magic_tokens",
        sa.Column(
            "mailing_address_country",
            sa.String(50),
            nullable=True,
            server_default="USA",
        ),
    )


def downgrade() -> None:
    for col in [
        "mailing_address_country",
        "mailing_address_postal_code",
        "mailing_address_state",
        "mailing_address_city",
        "mailing_address_line2",
        "mailing_address_line1",
    ]:
        op.drop_column("owner_magic_tokens", col)
