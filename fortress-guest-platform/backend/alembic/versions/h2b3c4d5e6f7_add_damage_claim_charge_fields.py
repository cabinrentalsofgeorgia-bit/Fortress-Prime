"""Add Stripe charge execution fields to damage_claims.

Revision ID: h2b3c4d5e6f7
Revises: h1a2b3c4d5e6
Create Date: 2026-04-11
"""

from __future__ import annotations

revision = "h2b3c4d5e6f7"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("damage_claims", sa.Column("stripe_charge_id", sa.String(255), nullable=True))
    op.add_column("damage_claims", sa.Column("amount_charged", sa.Numeric(10, 2), nullable=True))
    op.add_column("damage_claims", sa.Column("charge_payment_method_id", sa.String(255), nullable=True))
    op.add_column("damage_claims", sa.Column("charge_executed_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("damage_claims", sa.Column("charge_executed_by", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("damage_claims", "charge_executed_by")
    op.drop_column("damage_claims", "charge_executed_at")
    op.drop_column("damage_claims", "charge_payment_method_id")
    op.drop_column("damage_claims", "amount_charged")
    op.drop_column("damage_claims", "stripe_charge_id")
