"""I.1a: Add vendor_id, markup_percentage, vendor_amount to owner_charges.

Supports vendor attribution + manager markup on owner charges.
Semantics: owner sees `amount` (= vendor_amount × (1 + markup/100)).
           manager keeps amount - vendor_amount.

Revision ID: i1a2_add_vendor_and_markup
Revises: i1a1_add_owner_charge_types
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "i1a2_add_vendor_and_markup"
down_revision = "i1a1_add_owner_charge_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "owner_charges",
        sa.Column(
            "vendor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("vendors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "owner_charges",
        sa.Column(
            "markup_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.add_column(
        "owner_charges",
        sa.Column(
            "vendor_amount",
            sa.Numeric(12, 2),
            nullable=True,
            comment="Paid to vendor; owner amount = vendor_amount * (1 + markup/100)",
        ),
    )
    op.create_index("ix_owner_charges_vendor_id", "owner_charges", ["vendor_id"])


def downgrade() -> None:
    op.drop_index("ix_owner_charges_vendor_id", table_name="owner_charges")
    op.drop_column("owner_charges", "vendor_amount")
    op.drop_column("owner_charges", "markup_percentage")
    op.drop_column("owner_charges", "vendor_id")
