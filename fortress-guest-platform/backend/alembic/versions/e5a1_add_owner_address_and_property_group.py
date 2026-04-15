"""Phase E.5 — owner mailing address + property group.

  owner_payout_accounts: adds 6 mailing address columns (nullable).
  properties:            adds property_group column (nullable).

Revision ID: e5a1b2c3d4f5
Revises: e5merge01
Create Date: 2026-04-14
"""
from __future__ import annotations

revision = "e5a1b2c3d4f5"
down_revision = "e5merge01"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # ── owner_payout_accounts: mailing address ────────────────────────────────
    op.add_column(
        "owner_payout_accounts",
        sa.Column("mailing_address_line1", sa.String(255), nullable=True),
    )
    op.add_column(
        "owner_payout_accounts",
        sa.Column("mailing_address_line2", sa.String(255), nullable=True),
    )
    op.add_column(
        "owner_payout_accounts",
        sa.Column("mailing_address_city", sa.String(100), nullable=True),
    )
    op.add_column(
        "owner_payout_accounts",
        sa.Column("mailing_address_state", sa.String(50), nullable=True),
    )
    op.add_column(
        "owner_payout_accounts",
        sa.Column("mailing_address_postal_code", sa.String(20), nullable=True),
    )
    op.add_column(
        "owner_payout_accounts",
        sa.Column(
            "mailing_address_country",
            sa.String(50),
            nullable=True,
            server_default="USA",
        ),
    )

    # ── properties: property_group ────────────────────────────────────────────
    # Nullable permanently — 44 offboarded properties legitimately have no group.
    op.add_column(
        "properties",
        sa.Column("property_group", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("properties", "property_group")
    op.drop_column("owner_payout_accounts", "mailing_address_country")
    op.drop_column("owner_payout_accounts", "mailing_address_postal_code")
    op.drop_column("owner_payout_accounts", "mailing_address_state")
    op.drop_column("owner_payout_accounts", "mailing_address_city")
    op.drop_column("owner_payout_accounts", "mailing_address_line2")
    op.drop_column("owner_payout_accounts", "mailing_address_line1")
