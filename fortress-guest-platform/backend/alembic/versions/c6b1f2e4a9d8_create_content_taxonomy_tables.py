"""create content taxonomy tables

Revision ID: c6b1f2e4a9d8
Revises: a4f9c2d7e6b1
Create Date: 2026-03-22 11:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c6b1f2e4a9d8"
down_revision: Union[str, None] = "a4f9c2d7e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_taxonomy_categories_slug", "taxonomy_categories", ["slug"], unique=True)

    op.create_table(
        "marketing_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("content_body_html", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("published_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["taxonomy_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketing_articles_category_id", "marketing_articles", ["category_id"], unique=False)
    op.create_index("ix_marketing_articles_published_date", "marketing_articles", ["published_date"], unique=False)
    op.create_index("ix_marketing_articles_slug", "marketing_articles", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_marketing_articles_slug", table_name="marketing_articles")
    op.drop_index("ix_marketing_articles_published_date", table_name="marketing_articles")
    op.drop_index("ix_marketing_articles_category_id", table_name="marketing_articles")
    op.drop_table("marketing_articles")
    op.drop_index("ix_taxonomy_categories_slug", table_name="taxonomy_categories")
    op.drop_table("taxonomy_categories")
