"""Add SEORubric and SEOPatch Swarm pipeline tables

Revision ID: 8029df49b834
Revises: b7d9d40a1e6c
Create Date: 2026-03-20 20:46:27.080717

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8029df49b834"
down_revision: Union[str, Sequence[str], None] = "b7d9d40a1e6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align swarm SEO tables with the current blueprint."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    op.alter_column(
        "seo_rubrics",
        "keyword_cluster",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.create_index("ix_seo_rubrics_status", "seo_rubrics", ["status"], unique=False)

    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("seo_patches")}
    if "seo_patches_property_id_fkey" in existing_fks:
        op.drop_constraint("seo_patches_property_id_fkey", "seo_patches", type_="foreignkey")
    if "seo_patches_rubric_id_fkey" in existing_fks:
        op.drop_constraint("seo_patches_rubric_id_fkey", "seo_patches", type_="foreignkey")
    op.alter_column(
        "seo_patches",
        "property_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    if "properties" in tables:
        op.create_foreign_key(
            "seo_patches_property_id_fkey",
            "seo_patches",
            "properties",
            ["property_id"],
            ["id"],
        )
    op.create_foreign_key(
        "seo_patches_rubric_id_fkey",
        "seo_patches",
        "seo_rubrics",
        ["rubric_id"],
        ["id"],
    )


def downgrade() -> None:
    """Restore the previous swarm SEO table definitions."""
    op.drop_constraint("seo_patches_rubric_id_fkey", "seo_patches", type_="foreignkey")
    op.drop_constraint("seo_patches_property_id_fkey", "seo_patches", type_="foreignkey")
    op.alter_column(
        "seo_patches",
        "property_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "seo_patches_rubric_id_fkey",
        "seo_patches",
        "seo_rubrics",
        ["rubric_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "seo_patches_property_id_fkey",
        "seo_patches",
        "properties",
        ["property_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_seo_rubrics_status", table_name="seo_rubrics")
    op.alter_column(
        "seo_rubrics",
        "keyword_cluster",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=False,
    )
