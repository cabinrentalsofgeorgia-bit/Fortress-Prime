"""Add fee_type, percentage_rate, is_optional to fees table.

These columns are defined in the Fee ORM model (financial_primitives.py) but
were never migrated to the database, causing the SQL ledger quote path to fail
silently and fall through to the rate_card fallback.

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-04-12
"""
from __future__ import annotations

revision = "k6f7a8b9c0d1"
down_revision = "j5e6f7a8b9c0"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE fees ADD COLUMN IF NOT EXISTS fee_type VARCHAR(20) NOT NULL DEFAULT 'flat'"
    ))
    op.execute(sa.text(
        "ALTER TABLE fees ADD COLUMN IF NOT EXISTS percentage_rate NUMERIC(6,3)"
    ))
    op.execute(sa.text(
        "ALTER TABLE fees ADD COLUMN IF NOT EXISTS is_optional BOOLEAN NOT NULL DEFAULT false"
    ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE fees DROP COLUMN IF EXISTS is_optional"))
    op.execute(sa.text("ALTER TABLE fees DROP COLUMN IF EXISTS percentage_rate"))
    op.execute(sa.text("ALTER TABLE fees DROP COLUMN IF EXISTS fee_type"))
