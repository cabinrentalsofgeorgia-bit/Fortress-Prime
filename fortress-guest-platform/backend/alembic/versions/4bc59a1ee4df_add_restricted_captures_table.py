"""add restricted_captures table

Revision ID: 4bc59a1ee4df
Revises: i5a1_obp_payout_columns
Create Date: 2026-04-18

Parallel table to llm_training_captures for privileged content that is
retained for audit but never exported to training JSONL. Part of Iron
Dome Phase 2 (privilege filter).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "4bc59a1ee4df"
down_revision = "i5a1_obp_payout_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restricted_captures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.Column("source_persona", sa.String(128), nullable=True),
        sa.Column("source_module", sa.String(128), nullable=True),
        sa.Column("restriction_reason", sa.String(256), nullable=False),
        sa.Column(
            "matched_patterns",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("capture_metadata", postgresql.JSONB, nullable=True),
    )

    op.create_index(
        "idx_restricted_captures_created_at",
        "restricted_captures",
        ["created_at"],
    )
    op.create_index(
        "idx_restricted_captures_source_persona",
        "restricted_captures",
        ["source_persona"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_restricted_captures_source_persona",
        table_name="restricted_captures",
    )
    op.drop_index(
        "idx_restricted_captures_created_at",
        table_name="restricted_captures",
    )
    op.drop_table("restricted_captures")
