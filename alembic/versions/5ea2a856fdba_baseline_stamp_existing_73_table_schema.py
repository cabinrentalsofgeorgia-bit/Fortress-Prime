"""baseline: stamp existing 73-table schema

Revision ID: 5ea2a856fdba
Revises:
Create Date: 2026-02-12

This is the BASELINE migration. It does NOT re-create existing tables.
It stamps the alembic_version table to mark the current schema as tracked.

For a fresh install, run:  psql -f alembic/versions/baseline_schema.sql
Then:                       alembic stamp head

Schemas tracked: public (46 tables), division_a (7), division_b (8), engineering (12)
Total: 73 tables.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5ea2a856fdba'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Stamp baseline — tables already exist in production."""
    # Verify key tables exist (safety check)
    conn = op.get_bind()
    result = conn.execute(
        op.inline_literal(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    )
    count = result.scalar()
    if count < 10:
        raise RuntimeError(
            f"Expected 40+ tables in public schema, found {count}. "
            "Run baseline_schema.sql first: psql -f alembic/versions/baseline_schema.sql"
        )
    # Nothing to create — this is a stamp-only migration
    pass


def downgrade() -> None:
    """Cannot downgrade past baseline — would destroy the entire database."""
    raise RuntimeError(
        "Cannot downgrade past baseline migration. "
        "This would require dropping all 73 tables. Use pg_dump for backups."
    )
