"""Keep rollback reconciliation stable after repeat rollback no-op.

Revision ID: 0015_promotion_reconciliation_repeat_rollback
Revises: 0014_signal_health_dashboard
Create Date: 2026-05-04 20:05:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0015_promotion_reconciliation_repeat_rollback"
down_revision = "0014_signal_health_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_promotion_audit_observability.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    pass
