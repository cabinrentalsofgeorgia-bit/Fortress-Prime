"""Create nim_catalog table for NGC NIM/NeMo container inventory.

Stores metadata gathered by tools/ngc_catalog_enumerator.py: manifest-level
platform info, arm64 presence, entitlement status, size, model family, task
type, and a per-run JSONL snapshot path.  Probe runs are idempotent — each
(probe_date, image_path) pair is unique so re-runs upsert in place.

Revision ID: m8f9a1b2c3d4
Revises: l7e8f1a2b3c4
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "m8f9a1b2c3d4"
down_revision = "l7e8f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nim_catalog",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("probe_date", sa.Date(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("latest_tag", sa.Text()),
        sa.Column(
            "tags_available",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "platforms",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("arm64_manifest_present", sa.Boolean()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("model_family", sa.Text()),
        sa.Column("task_type", sa.Text()),
        sa.Column("license_hint", sa.Text()),
        sa.Column("publication_date", sa.TIMESTAMP(timezone=True)),
        sa.Column("entitlement_status", sa.Text()),
        sa.Column("description_snippet", sa.Text()),
        sa.Column("probe_notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("probe_date", "image_path", name="uq_nim_catalog_probe_date_image"),
    )

    op.create_index("idx_nim_catalog_family", "nim_catalog", ["model_family"])
    op.create_index("idx_nim_catalog_task", "nim_catalog", ["task_type"])
    op.create_index("idx_nim_catalog_arm64", "nim_catalog", ["arm64_manifest_present"])

    # Grant runtime user access
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON nim_catalog TO fortress_api"))
    op.execute(sa.text("GRANT USAGE, SELECT ON SEQUENCE nim_catalog_id_seq TO fortress_api"))


def downgrade() -> None:
    op.execute(sa.text("REVOKE ALL ON nim_catalog FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON SEQUENCE nim_catalog_id_seq FROM fortress_api"))
    op.drop_index("idx_nim_catalog_arm64", table_name="nim_catalog")
    op.drop_index("idx_nim_catalog_task", table_name="nim_catalog")
    op.drop_index("idx_nim_catalog_family", table_name="nim_catalog")
    op.drop_table("nim_catalog")
