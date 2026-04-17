"""add_cleaners_table_and_assigned_cleaner_fk

Revision ID: 8bc70dafda91
Revises: d07f15298db8
Create Date: 2026-04-13 19:07:35.171947

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8bc70dafda91'
down_revision: Union[str, Sequence[str], None] = 'd07f15298db8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create cleaners table
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS cleaners (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(200) NOT NULL,
            phone           VARCHAR(40),
            email           VARCHAR(255),
            active          BOOLEAN     NOT NULL DEFAULT true,
            per_clean_rate  NUMERIC(8,2),
            hourly_rate     NUMERIC(8,2),
            property_ids    JSONB       NOT NULL DEFAULT '[]',
            regions         JSONB       NOT NULL DEFAULT '[]',
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_cleaners_active ON cleaners (active)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON cleaners TO fortress_api"
    ))

    # 2. Add legacy_assigned_to to preserve existing string values,
    #    and assigned_cleaner_id FK for structured assignment.
    op.execute(sa.text("""
        ALTER TABLE housekeeping_tasks
            ADD COLUMN IF NOT EXISTS legacy_assigned_to VARCHAR(255),
            ADD COLUMN IF NOT EXISTS assigned_cleaner_id UUID
                REFERENCES cleaners(id) ON DELETE SET NULL
    """))

    # 3. Copy existing assigned_to values to legacy_assigned_to
    op.execute(sa.text("""
        UPDATE housekeeping_tasks
        SET legacy_assigned_to = assigned_to
        WHERE assigned_to IS NOT NULL AND assigned_to != ''
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_housekeeping_tasks_cleaner "
        "ON housekeeping_tasks (assigned_cleaner_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE housekeeping_tasks "
        "DROP COLUMN IF EXISTS assigned_cleaner_id, "
        "DROP COLUMN IF EXISTS legacy_assigned_to"
    ))
    op.execute(sa.text("DROP TABLE IF EXISTS cleaners"))
