"""add_voided_paid_by_to_balance_periods

Phase D: adds voided_at, voided_by, and paid_by to
owner_balance_periods so every lifecycle transition has
a timestamp + user attribution.

Phase A created approved_at / approved_by / paid_at / emailed_at
but omitted voided_at, voided_by, and paid_by.

Revision ID: f1e2d3c4b5a6
Revises: c9e2f4a7b1d3
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "c9e2f4a7b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE owner_balance_periods
            ADD COLUMN voided_at   TIMESTAMPTZ,
            ADD COLUMN voided_by   VARCHAR(255),
            ADD COLUMN paid_by     VARCHAR(255)
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE owner_balance_periods
            DROP COLUMN IF EXISTS voided_at,
            DROP COLUMN IF EXISTS voided_by,
            DROP COLUMN IF EXISTS paid_by
    """))
