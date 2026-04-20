"""refine seo patch and rubric tables

Revision ID: 4f6a8f7d2b21
Revises: 8029df49b834
Create Date: 2026-03-21 00:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f6a8f7d2b21"
down_revision: Union[str, None] = "8029df49b834"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    op.alter_column(
        "seo_rubrics",
        "source_model",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "seo_rubrics",
        "status",
        existing_type=sa.String(),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.create_index(
        "ix_seo_rubrics_keyword_cluster",
        "seo_rubrics",
        ["keyword_cluster"],
        unique=False,
    )

    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("seo_patches")}
    if "seo_patches_property_id_fkey" in existing_fks:
        op.drop_constraint("seo_patches_property_id_fkey", "seo_patches", type_="foreignkey")
    if "seo_patches_rubric_id_fkey" in existing_fks:
        op.drop_constraint("seo_patches_rubric_id_fkey", "seo_patches", type_="foreignkey")
    if "properties" in tables:
        op.create_foreign_key(
            "seo_patches_property_id_fkey",
            "seo_patches",
            "properties",
            ["property_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_foreign_key(
        "seo_patches_rubric_id_fkey",
        "seo_patches",
        "seo_rubrics",
        ["rubric_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column(
        "seo_patches",
        "title",
        existing_type=sa.String(length=70),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "meta_description",
        existing_type=sa.String(length=320),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "og_title",
        existing_type=sa.String(length=95),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "og_description",
        existing_type=sa.String(length=200),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "canonical_url",
        existing_type=sa.String(),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "h1_suggestion",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "godhead_model",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "status",
        existing_type=sa.String(),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "seo_patches",
        "reviewed_by",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "swarm_model",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "swarm_node",
        existing_type=sa.String(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.create_index(
        "ix_seo_patches_rubric_id",
        "seo_patches",
        ["rubric_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_patches_rubric_id", table_name="seo_patches")
    op.alter_column(
        "seo_patches",
        "swarm_node",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "swarm_model",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "reviewed_by",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "status",
        existing_type=sa.String(length=50),
        type_=sa.String(),
        existing_nullable=False,
    )
    op.alter_column(
        "seo_patches",
        "godhead_model",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "h1_suggestion",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "canonical_url",
        existing_type=sa.String(length=2048),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "og_description",
        existing_type=sa.Text(),
        type_=sa.String(length=200),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "og_title",
        existing_type=sa.String(length=255),
        type_=sa.String(length=95),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "meta_description",
        existing_type=sa.Text(),
        type_=sa.String(length=320),
        existing_nullable=True,
    )
    op.alter_column(
        "seo_patches",
        "title",
        existing_type=sa.String(length=255),
        type_=sa.String(length=70),
        existing_nullable=True,
    )

    op.drop_constraint("seo_patches_rubric_id_fkey", "seo_patches", type_="foreignkey")
    op.drop_constraint("seo_patches_property_id_fkey", "seo_patches", type_="foreignkey")
    op.create_foreign_key(
        "seo_patches_rubric_id_fkey",
        "seo_patches",
        "seo_rubrics",
        ["rubric_id"],
        ["id"],
    )
    op.create_foreign_key(
        "seo_patches_property_id_fkey",
        "seo_patches",
        "properties",
        ["property_id"],
        ["id"],
    )

    op.drop_index("ix_seo_rubrics_keyword_cluster", table_name="seo_rubrics")
    op.alter_column(
        "seo_rubrics",
        "status",
        existing_type=sa.String(length=50),
        type_=sa.String(),
        existing_nullable=False,
    )
    op.alter_column(
        "seo_rubrics",
        "source_model",
        existing_type=sa.String(length=255),
        type_=sa.String(),
        existing_nullable=False,
    )
