"""add seo deploy acknowledgment fields

Revision ID: 2c5f4a8e1b7d
Revises: d4e6f8a1b2c3
Create Date: 2026-03-22 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2c5f4a8e1b7d"
down_revision: Union[str, None] = "d4e6f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("seo_patches")}

    if "deploy_task_id" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_task_id", postgresql.UUID(as_uuid=True), nullable=True))
    if "deploy_status" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_status", sa.String(length=50), nullable=True))
    if "deploy_queued_at" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_queued_at", sa.DateTime(timezone=True), nullable=True))
    if "deploy_acknowledged_at" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    if "deploy_attempts" not in columns:
        op.add_column(
            "seo_patches",
            sa.Column("deploy_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if "deploy_last_error" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_last_error", sa.Text(), nullable=True))
    if "deploy_last_http_status" not in columns:
        op.add_column("seo_patches", sa.Column("deploy_last_http_status", sa.Integer(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("seo_patches")}
    if "ix_seo_patches_deploy_status" not in indexes:
        op.create_index("ix_seo_patches_deploy_status", "seo_patches", ["deploy_status"], unique=False)
    if "ix_seo_patches_deploy_acknowledged_at" not in indexes:
        op.create_index(
            "ix_seo_patches_deploy_acknowledged_at",
            "seo_patches",
            ["deploy_acknowledged_at"],
            unique=False,
        )

    bind.execute(
        sa.text(
            """
            UPDATE seo_patches
            SET
                deploy_status = CASE
                    WHEN status = 'deployed' THEN 'succeeded'
                    ELSE deploy_status
                END,
                deploy_queued_at = CASE
                    WHEN status = 'deployed' THEN COALESCE(deploy_queued_at, deployed_at, updated_at, created_at)
                    ELSE deploy_queued_at
                END,
                deploy_acknowledged_at = CASE
                    WHEN status = 'deployed' THEN COALESCE(deploy_acknowledged_at, deployed_at, updated_at, created_at)
                    ELSE deploy_acknowledged_at
                END,
                deploy_attempts = CASE
                    WHEN status = 'deployed' AND COALESCE(deploy_attempts, 0) = 0 THEN 1
                    ELSE COALESCE(deploy_attempts, 0)
                END
            WHERE status = 'deployed' OR deploy_status IS NOT NULL
            """
        )
    )

    bind.execute(sa.text("ALTER TABLE seo_patches ALTER COLUMN deploy_attempts DROP DEFAULT"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("seo_patches")}
    indexes = {index["name"] for index in inspector.get_indexes("seo_patches")}

    if "ix_seo_patches_deploy_acknowledged_at" in indexes:
        op.drop_index("ix_seo_patches_deploy_acknowledged_at", table_name="seo_patches")
    if "ix_seo_patches_deploy_status" in indexes:
        op.drop_index("ix_seo_patches_deploy_status", table_name="seo_patches")

    for column_name in (
        "deploy_last_http_status",
        "deploy_last_error",
        "deploy_attempts",
        "deploy_acknowledged_at",
        "deploy_queued_at",
        "deploy_status",
        "deploy_task_id",
    ):
        if column_name in columns:
            op.drop_column("seo_patches", column_name)
