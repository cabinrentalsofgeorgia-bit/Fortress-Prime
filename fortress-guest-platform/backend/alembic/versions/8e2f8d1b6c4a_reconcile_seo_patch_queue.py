"""reconcile seo patch queue

Revision ID: 8e2f8d1b6c4a
Revises: f6a8b0c2d4e5
Create Date: 2026-03-22 01:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8e2f8d1b6c4a"
down_revision: Union[str, None] = "f6a8b0c2d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("seo_patch_queue"):
        op.create_table(
            "seo_patch_queue",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("target_type", sa.String(length=32), nullable=False),
            sa.Column("target_slug", sa.String(length=255), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("target_keyword", sa.String(length=255), nullable=True),
            sa.Column("campaign", sa.String(length=100), nullable=False),
            sa.Column("rubric_version", sa.String(length=50), nullable=True),
            sa.Column("source_hash", sa.String(length=128), nullable=False),
            sa.Column("proposed_title", sa.String(length=255), nullable=False),
            sa.Column("proposed_meta_description", sa.Text(), nullable=False),
            sa.Column("proposed_h1", sa.String(length=255), nullable=False),
            sa.Column("proposed_intro", sa.Text(), nullable=False),
            sa.Column(
                "proposed_faq",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "proposed_json_ld",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "fact_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("score_overall", sa.Float(), nullable=True),
            sa.Column(
                "score_breakdown",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("proposed_by", sa.String(length=100), nullable=False),
            sa.Column("proposal_run_id", sa.String(length=100), nullable=True),
            sa.Column("reviewed_by", sa.String(length=100), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column(
                "approved_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("approved_at", sa.TIMESTAMP(), nullable=True),
            sa.Column("deployed_at", sa.TIMESTAMP(), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "status IN ('proposed','needs_revision','approved','rejected','deployed','superseded')",
                name="ck_seo_patch_queue_status",
            ),
            sa.CheckConstraint(
                "target_type IN ('property','archive_review')",
                name="ck_seo_patch_queue_target_type",
            ),
            sa.ForeignKeyConstraint(
                ["property_id"],
                ["properties.id"],
                name="seo_patch_queue_property_id_fkey",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "target_type",
                "target_slug",
                "campaign",
                "source_hash",
                name="uq_seo_patch_queue_target_campaign_source",
            ),
        )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_type "
            "ON seo_patch_queue (target_type)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_slug "
            "ON seo_patch_queue (target_slug)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_property_id "
            "ON seo_patch_queue (property_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_status "
            "ON seo_patch_queue (status)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_campaign "
            "ON seo_patch_queue (campaign)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_created_at "
            "ON seo_patch_queue (created_at)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_status_created "
            "ON seo_patch_queue (status, created_at)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_approved "
            "ON seo_patch_queue (target_type, target_slug, approved_at)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_property_approved "
            "ON seo_patch_queue (property_id, approved_at)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS seo_patch_queue CASCADE"))
