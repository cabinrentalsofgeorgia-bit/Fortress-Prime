"""Add read-only rollback drill observability.

Revision ID: 0008_rollback_drill_observability
Revises: 0007_guarded_promotion_execution
Create Date: 2026-05-04 09:15:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0008_rollback_drill_observability"
down_revision = "0007_guarded_promotion_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_rollback_drill_observability.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_rollback_drill")
