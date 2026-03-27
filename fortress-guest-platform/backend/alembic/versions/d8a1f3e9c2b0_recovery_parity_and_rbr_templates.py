"""recovery parity comparisons and rue ba rue legacy templates

Revision ID: d8a1f3e9c2b0
Revises: c3f9a7d6e2b1
Create Date: 2026-03-24 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d8a1f3e9c2b0"
down_revision: Union[str, Sequence[str], None] = "c3f9a7d6e2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rue_bar_rue_legacy_recovery_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("audience_rule", sa.String(length=64), server_default="*", nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_system", sa.String(length=64), server_default="rue_ba_rue", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", name="uq_rbr_legacy_recovery_template_key"),
    )
    op.create_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_audience_rule"), "rue_bar_rue_legacy_recovery_templates", ["audience_rule"], unique=False)
    op.create_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_channel"), "rue_bar_rue_legacy_recovery_templates", ["channel"], unique=False)
    op.create_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_template_key"), "rue_bar_rue_legacy_recovery_templates", ["template_key"], unique=False)

    op.create_table(
        "recovery_parity_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
        sa.Column("session_fp", sa.String(length=128), nullable=False),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_slug", sa.String(length=255), nullable=True),
        sa.Column("drop_off_point", sa.String(length=64), nullable=False),
        sa.Column("intent_score_estimate", sa.Float(), nullable=False),
        sa.Column("legacy_template_key", sa.String(length=80), nullable=False),
        sa.Column("legacy_body", sa.Text(), nullable=False),
        sa.Column("sovereign_body", sa.Text(), nullable=False),
        sa.Column("parity_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("candidate_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("async_job_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_hash", name="uq_recovery_parity_comparisons_dedupe_hash"),
    )
    op.create_index(op.f("ix_recovery_parity_comparisons_created_at"), "recovery_parity_comparisons", ["created_at"], unique=False)
    op.create_index(op.f("ix_recovery_parity_comparisons_dedupe_hash"), "recovery_parity_comparisons", ["dedupe_hash"], unique=False)
    op.create_index(op.f("ix_recovery_parity_comparisons_guest_id"), "recovery_parity_comparisons", ["guest_id"], unique=False)
    op.create_index("ix_recovery_parity_guest_created", "recovery_parity_comparisons", ["guest_id", "created_at"], unique=False)
    op.create_index(op.f("ix_recovery_parity_comparisons_session_fp"), "recovery_parity_comparisons", ["session_fp"], unique=False)
    op.create_index("ix_recovery_parity_session_fp_created", "recovery_parity_comparisons", ["session_fp", "created_at"], unique=False)
    op.create_index(op.f("ix_recovery_parity_comparisons_async_job_run_id"), "recovery_parity_comparisons", ["async_job_run_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO rue_bar_rue_legacy_recovery_templates
                (id, template_key, channel, audience_rule, body_template, is_active, source_system)
            VALUES
                (gen_random_uuid(), 'rue_bar_rue_generic_v1', 'sms', '*',
                 'Hi {first_name}, thanks for your interest in a Blue Ridge stay. '
                 'We received your form and will follow up with more details soon. — Rue Ba Rue',
                 true, 'rue_ba_rue')
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_recovery_parity_comparisons_async_job_run_id"), table_name="recovery_parity_comparisons")
    op.drop_index("ix_recovery_parity_session_fp_created", table_name="recovery_parity_comparisons")
    op.drop_index(op.f("ix_recovery_parity_comparisons_session_fp"), table_name="recovery_parity_comparisons")
    op.drop_index("ix_recovery_parity_guest_created", table_name="recovery_parity_comparisons")
    op.drop_index(op.f("ix_recovery_parity_comparisons_guest_id"), table_name="recovery_parity_comparisons")
    op.drop_index(op.f("ix_recovery_parity_comparisons_dedupe_hash"), table_name="recovery_parity_comparisons")
    op.drop_index(op.f("ix_recovery_parity_comparisons_created_at"), table_name="recovery_parity_comparisons")
    op.drop_table("recovery_parity_comparisons")
    op.drop_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_template_key"), table_name="rue_bar_rue_legacy_recovery_templates")
    op.drop_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_channel"), table_name="rue_bar_rue_legacy_recovery_templates")
    op.drop_index(op.f("ix_rue_bar_rue_legacy_recovery_templates_audience_rule"), table_name="rue_bar_rue_legacy_recovery_templates")
    op.drop_table("rue_bar_rue_legacy_recovery_templates")
