"""Add promotion dry-run verification helper.

Revision ID: 0006_promotion_dry_run_verification
Revises: 0005_promotion_dry_run_acceptances
Create Date: 2026-05-04
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0006_promotion_dry_run_verification"
down_revision = "0005_promotion_dry_run_acceptances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "sql"
        / "marketclub_promotion_dry_run_verification.sql"
    )
    op.execute(sql_path.read_text())


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS hedge_fund.verify_promotion_dry_run(TEXT, TEXT)"
    )
