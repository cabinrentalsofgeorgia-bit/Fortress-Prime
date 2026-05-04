"""Add backend-locked operator rollback action audit.

Revision ID: 0009_operator_rollback_action
Revises: 0008_rollback_drill_observability
Create Date: 2026-05-04 11:05:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0009_operator_rollback_action"
down_revision = "0008_rollback_drill_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_operator_rollback_action.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_promotion_rollback_audits")
