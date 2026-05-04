"""Add post-execution promotion monitoring.

Revision ID: 0011_post_execution_monitoring
Revises: 0010_promotion_audit_observability
Create Date: 2026-05-04 13:05:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0011_post_execution_monitoring"
down_revision = "0010_promotion_audit_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_post_execution_monitoring.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_post_execution_monitoring")
