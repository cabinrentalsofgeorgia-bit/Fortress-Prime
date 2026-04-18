"""I.2/I.3: Add owner_payment_received to owner_charge_type_enum.

Phase I.2 (Receive Owner Payment) stores payments from owner as negative
owner_charge entries with transaction_type=owner_payment_received.

Phase I.3 (Credit Owner Account) reuses existing codes:
  credit_from_management — already present from original 17-code set
  adjust_owner_revenue   — already present from original 17-code set

Only one new enum value is needed.

Revision ID: i23a1_add_payment_credit_codes
Revises: i5a1_obp_payout_columns
Create Date: 2026-04-16
"""
from __future__ import annotations

from alembic import op

revision = "i23a1_add_payment_credit_codes"
down_revision = "i5a1_obp_payout_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE owner_charge_type_enum ADD VALUE IF NOT EXISTS 'owner_payment_received'"
    )


def downgrade() -> None:
    # Postgres does not support removing enum values — intentional no-op.
    pass
