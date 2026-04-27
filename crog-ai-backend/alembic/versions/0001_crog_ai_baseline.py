"""baseline: crog-ai chain initialized in hedge_fund schema

Revision ID: 0001_crog_ai_baseline
Revises:
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text


revision: str = "0001_crog_ai_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Verify the hedge_fund schema exists. No schema changes."""
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.schemata "
            "WHERE schema_name = 'hedge_fund'"
        )
    ).scalar()
    if result != 1:
        raise RuntimeError(
            "hedge_fund schema does not exist in the target database. "
            "Verify DATABASE_URL points at fortress_db (not fortress_prod)."
        )


def downgrade() -> None:
    pass
