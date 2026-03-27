"""add scout traceability and targeting

Revision ID: f1a2b3c4d5e6
Revises: c1a9d7e4f2b3
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c1a9d7e4f2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    intelligence_columns = {column["name"] for column in inspector.get_columns("intelligence_ledger")}
    if "target_property_ids" not in intelligence_columns:
        op.add_column(
            "intelligence_ledger",
            sa.Column(
                "target_property_ids",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    if "target_tags" not in intelligence_columns:
        op.add_column(
            "intelligence_ledger",
            sa.Column(
                "target_tags",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

    seo_columns = {column["name"] for column in inspector.get_columns("seo_patches")}
    if "source_intelligence_id" not in seo_columns:
        op.add_column(
            "seo_patches",
            sa.Column("source_intelligence_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_seo_patches_source_intelligence_id",
            "seo_patches",
            "intelligence_ledger",
            ["source_intelligence_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "source_agent" not in seo_columns:
        op.add_column(
            "seo_patches",
            sa.Column("source_agent", sa.String(length=120), nullable=False, server_default="seo_patch_api"),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "seo_patches", "ix_seo_patches_source_intelligence_id"):
        op.create_index("ix_seo_patches_source_intelligence_id", "seo_patches", ["source_intelligence_id"])
    if not _has_index(inspector, "seo_patches", "ix_seo_patches_source_agent"):
        op.create_index("ix_seo_patches_source_agent", "seo_patches", ["source_agent"])

    if not inspector.has_table("distillation_queue"):
        op.create_table(
            "distillation_queue",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source_module", sa.String(length=120), nullable=False),
            sa.Column("source_ref", sa.String(length=255), nullable=False),
            sa.Column("source_intelligence_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "input_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "output_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "queued",
                    "processing",
                    "ready",
                    "failed",
                    name="distillation_status",
                    native_enum=False,
                ),
                nullable=False,
                server_default="queued",
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_intelligence_id"],
                ["intelligence_ledger.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_distillation_queue_source_module"),
            "distillation_queue",
            ["source_module"],
            unique=False,
        )
        op.create_index(
            op.f("ix_distillation_queue_source_ref"),
            "distillation_queue",
            ["source_ref"],
            unique=False,
        )
        op.create_index(
            op.f("ix_distillation_queue_status"),
            "distillation_queue",
            ["status"],
            unique=False,
        )
        op.create_index(
            op.f("ix_distillation_queue_source_intelligence_id"),
            "distillation_queue",
            ["source_intelligence_id"],
            unique=False,
        )
    else:
        distillation_columns = {column["name"] for column in inspector.get_columns("distillation_queue")}
        if "source_intelligence_id" not in distillation_columns:
            op.add_column(
                "distillation_queue",
                sa.Column("source_intelligence_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fk_distillation_queue_source_intelligence_id",
                "distillation_queue",
                "intelligence_ledger",
                ["source_intelligence_id"],
                ["id"],
                ondelete="SET NULL",
            )
        inspector = sa.inspect(bind)
        if not _has_index(inspector, "distillation_queue", op.f("ix_distillation_queue_source_intelligence_id")):
            op.create_index(
                op.f("ix_distillation_queue_source_intelligence_id"),
                "distillation_queue",
                ["source_intelligence_id"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("distillation_queue"):
        indexes = {index.get("name") for index in inspector.get_indexes("distillation_queue")}
        for index_name in (
            op.f("ix_distillation_queue_source_intelligence_id"),
            op.f("ix_distillation_queue_status"),
            op.f("ix_distillation_queue_source_ref"),
            op.f("ix_distillation_queue_source_module"),
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="distillation_queue")
        op.drop_table("distillation_queue")

    if inspector.has_table("seo_patches"):
        indexes = {index.get("name") for index in inspector.get_indexes("seo_patches")}
        if "ix_seo_patches_source_agent" in indexes:
            op.drop_index("ix_seo_patches_source_agent", table_name="seo_patches")
        if "ix_seo_patches_source_intelligence_id" in indexes:
            op.drop_index("ix_seo_patches_source_intelligence_id", table_name="seo_patches")
        seo_columns = {column["name"] for column in inspector.get_columns("seo_patches")}
        foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("seo_patches")}
        if "fk_seo_patches_source_intelligence_id" in foreign_keys:
            op.drop_constraint("fk_seo_patches_source_intelligence_id", "seo_patches", type_="foreignkey")
        if "source_agent" in seo_columns:
            op.drop_column("seo_patches", "source_agent")
        if "source_intelligence_id" in seo_columns:
            op.drop_column("seo_patches", "source_intelligence_id")

    intelligence_columns = {column["name"] for column in inspector.get_columns("intelligence_ledger")}
    if "target_tags" in intelligence_columns:
        op.drop_column("intelligence_ledger", "target_tags")
    if "target_property_ids" in intelligence_columns:
        op.drop_column("intelligence_ledger", "target_property_ids")
