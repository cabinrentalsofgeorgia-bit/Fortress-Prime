"""Add post-execution promotion alerts.

Revision ID: 0012_post_execution_alerts
Revises: 0011_post_execution_monitoring
Create Date: 2026-05-04 13:35:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0012_post_execution_alerts"
down_revision = "0011_post_execution_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_post_execution_alerts.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_post_execution_alerts")
