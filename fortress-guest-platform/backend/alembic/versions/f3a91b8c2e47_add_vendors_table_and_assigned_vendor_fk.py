"""add_vendors_table_and_assigned_vendor_fk

Revision ID: f3a91b8c2e47
Revises: 8bc70dafda91
Create Date: 2026-04-13 19:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a91b8c2e47'
down_revision: Union[str, Sequence[str], None] = '8bc70dafda91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create vendors table
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vendors (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            name             VARCHAR(200) NOT NULL,
            trade            VARCHAR(80),
            phone            VARCHAR(40),
            email            VARCHAR(255),
            insurance_expiry DATE,
            active           BOOLEAN      NOT NULL DEFAULT true,
            hourly_rate      NUMERIC(8,2),
            regions          JSONB        NOT NULL DEFAULT '[]',
            notes            TEXT,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_vendors_active ON vendors (active)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_vendors_trade ON vendors (trade)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON vendors TO fortress_api"
    ))

    # 2. Add assigned_vendor_id FK to work_orders
    #    Preserve existing free-text assigned_to in new legacy_assigned_to column.
    op.execute(sa.text("""
        ALTER TABLE work_orders
            ADD COLUMN IF NOT EXISTS legacy_assigned_to VARCHAR(255),
            ADD COLUMN IF NOT EXISTS assigned_vendor_id UUID
                REFERENCES vendors(id) ON DELETE SET NULL
    """))

    # 3. Copy existing assigned_to → legacy_assigned_to
    op.execute(sa.text("""
        UPDATE work_orders
        SET legacy_assigned_to = assigned_to
        WHERE assigned_to IS NOT NULL AND assigned_to != ''
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_work_orders_vendor "
        "ON work_orders (assigned_vendor_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE work_orders "
        "DROP COLUMN IF EXISTS assigned_vendor_id, "
        "DROP COLUMN IF EXISTS legacy_assigned_to"
    ))
    op.execute(sa.text("DROP TABLE IF EXISTS vendors"))
