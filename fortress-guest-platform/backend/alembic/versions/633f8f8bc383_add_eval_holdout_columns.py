"""add eval_holdout columns to capture tables

Revision ID: 633f8f8bc383
Revises: 4bc59a1ee4df
Create Date: 2026-04-18

Adds eval_holdout boolean to llm_training_captures and restricted_captures.
Rows marked True are held out from the training export and used only for
nightly eval (Phase 4b). Default False — existing rows stay in training.
"""
from alembic import op
import sqlalchemy as sa

revision = "633f8f8bc383"
down_revision = "4bc59a1ee4df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_training_captures",
        sa.Column("eval_holdout", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "idx_llm_training_captures_eval_holdout",
        "llm_training_captures",
        ["eval_holdout"],
    )

    op.add_column(
        "restricted_captures",
        sa.Column("eval_holdout", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "idx_restricted_captures_eval_holdout",
        "restricted_captures",
        ["eval_holdout"],
    )


def downgrade() -> None:
    op.drop_index("idx_restricted_captures_eval_holdout", table_name="restricted_captures")
    op.drop_column("restricted_captures", "eval_holdout")
    op.drop_index("idx_llm_training_captures_eval_holdout", table_name="llm_training_captures")
    op.drop_column("llm_training_captures", "eval_holdout")
