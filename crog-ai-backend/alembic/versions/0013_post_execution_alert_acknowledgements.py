"""Add post-execution alert acknowledgements.

Revision ID: 0013_post_execution_alert_acknowledgements
Revises: 0012_post_execution_alerts
Create Date: 2026-05-04 15:15:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0013_post_execution_alert_acknowledgements"
down_revision = "0012_post_execution_alerts"
branch_labels = None
depends_on = None


def _sql_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "deploy" / "sql" / name


def upgrade() -> None:
    op.execute(
        _sql_path("marketclub_post_execution_alert_acknowledgements.sql").read_text(
            encoding="utf-8"
        )
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_post_execution_alerts")
    op.execute(
        """
        DROP FUNCTION IF EXISTS hedge_fund.acknowledge_signal_promotion_alert(
            TEXT,
            TEXT,
            TEXT,
            TEXT
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_promotion_alert_acknowledgements")
    op.execute(
        _sql_path("marketclub_post_execution_alerts.sql").read_text(encoding="utf-8")
    )
