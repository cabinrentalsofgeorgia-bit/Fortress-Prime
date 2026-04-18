"""I.5: Add stripe_transfer_id and paid_amount to owner_balance_periods.

Stores Stripe Transfer ID and the exact dollar amount transferred for
audit and double-pay prevention queries.

Revision ID: i5a1_obp_payout_columns
Revises: i1a2_add_vendor_and_markup
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i5a1_obp_payout_columns"
down_revision = "i1a2_add_vendor_and_markup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "owner_balance_periods",
        sa.Column("stripe_transfer_id", sa.String(100), nullable=True,
                  comment="Stripe Transfer ID (tr_...) set on successful pay_owner call"),
    )
    op.add_column(
        "owner_balance_periods",
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=True,
                  comment="Amount transferred to owner (closing - opening at time of payment)"),
    )
    op.create_index(
        "ix_obp_stripe_transfer_id", "owner_balance_periods", ["stripe_transfer_id"],
        postgresql_where=sa.text("stripe_transfer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_obp_stripe_transfer_id", table_name="owner_balance_periods")
    op.drop_column("owner_balance_periods", "paid_amount")
    op.drop_column("owner_balance_periods", "stripe_transfer_id")
