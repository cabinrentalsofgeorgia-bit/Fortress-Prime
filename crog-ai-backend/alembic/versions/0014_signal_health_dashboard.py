"""Add read-only signal health dashboard.

Revision ID: 0014_signal_health_dashboard
Revises: 0013_post_execution_alert_acknowledgements
Create Date: 2026-05-04 16:30:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0014_signal_health_dashboard"
down_revision = "0013_post_execution_alert_acknowledgements"
branch_labels = None
depends_on = None


def _sql_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "deploy" / "sql" / name


def upgrade() -> None:
    op.execute(
        _sql_path("marketclub_signal_health_dashboard.sql").read_text(encoding="utf-8")
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS hedge_fund.signal_health_model_divergence(
            TEXT,
            TEXT,
            INTEGER
        )
        """
    )
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_health_execution_outcomes")
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_health_at_risk_signals")
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_health_active_promotions")
