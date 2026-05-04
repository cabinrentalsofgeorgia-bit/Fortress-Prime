"""Add promotion lifecycle audit observability.

Revision ID: 0010_promotion_audit_observability
Revises: 0009_operator_rollback_action
Create Date: 2026-05-04 12:35:00.000000
"""

from pathlib import Path

from alembic import op

revision = "0010_promotion_audit_observability"
down_revision = "0009_operator_rollback_action"
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
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_reconciliation")
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_promotion_lifecycle_timeline")
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_signal_promotion_rollback_snapshot_hash
        ON hedge_fund.signal_promotion_rollback_audits
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_signal_promotion_execution_snapshot_hash
        ON hedge_fund.signal_promotion_executions
        """
    )
    op.execute("DROP FUNCTION IF EXISTS hedge_fund.set_signal_promotion_rollback_snapshot_hash()")
    op.execute("DROP FUNCTION IF EXISTS hedge_fund.set_signal_promotion_execution_snapshot_hash()")
    op.execute(
        """
        ALTER TABLE hedge_fund.signal_promotion_rollback_audits
            DROP COLUMN IF EXISTS deleted_market_signal_ids_hash
        """
    )
    op.execute(
        """
        ALTER TABLE hedge_fund.signal_promotion_executions
            DROP COLUMN IF EXISTS inserted_market_signal_ids_hash
        """
    )
    op.execute(
        """
        ALTER TABLE hedge_fund.signal_promotion_dry_run_acceptances
            DROP COLUMN IF EXISTS candidate_set_hash,
            DROP COLUMN IF EXISTS verification_payload_snapshot,
            DROP COLUMN IF EXISTS verification_status_snapshot
        """
    )
