"""Add guarded promotion execution path.

Revision ID: 0007_guarded_promotion_execution
Revises: 0006_promotion_dry_run_verification
Create Date: 2026-05-04 08:10:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0007_guarded_promotion_execution"
down_revision = "0006_promotion_dry_run_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_guarded_promotion_execution.sql"
    )
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS hedge_fund.rollback_guarded_signal_promotion(UUID, TEXT, TEXT)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS hedge_fund.execute_guarded_signal_promotion(UUID, TEXT, TEXT, TEXT)"
    )
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_promotion_execution_rows")
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_promotion_executions")
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_operator_memberships")
