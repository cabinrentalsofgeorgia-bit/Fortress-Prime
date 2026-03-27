"""create functional_nodes table

Revision ID: a13f4c7d9b21
Revises: f9b2c3d4e5a6
Create Date: 2026-03-24 07:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a13f4c7d9b21"
down_revision: Union[str, Sequence[str], None] = "f9b2c3d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "functional_nodes" in inspector.get_table_names():
        return

    op.create_table(
        "functional_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legacy_node_id", sa.Integer(), nullable=True),
        sa.Column("source_path", sa.String(length=255), nullable=False),
        sa.Column("canonical_path", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("content_category", sa.String(length=64), nullable=False),
        sa.Column("functional_complexity", sa.String(length=64), nullable=False),
        sa.Column("crawl_status", sa.String(length=32), server_default="discovered", nullable=False),
        sa.Column("mirror_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("cutover_status", sa.String(length=32), server_default="legacy", nullable=False),
        sa.Column("priority_tier", sa.Integer(), server_default="50", nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_text_preview", sa.Text(), nullable=True),
        sa.Column(
            "form_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "taxonomy_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "media_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("mirror_component_path", sa.String(length=512), nullable=True),
        sa.Column("mirror_route_path", sa.String(length=512), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("last_crawled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_functional_nodes_legacy_node_id"), "functional_nodes", ["legacy_node_id"], unique=False)
    op.create_index(op.f("ix_functional_nodes_source_path"), "functional_nodes", ["source_path"], unique=True)
    op.create_index(op.f("ix_functional_nodes_canonical_path"), "functional_nodes", ["canonical_path"], unique=True)
    op.create_index(op.f("ix_functional_nodes_node_type"), "functional_nodes", ["node_type"], unique=False)
    op.create_index(op.f("ix_functional_nodes_content_category"), "functional_nodes", ["content_category"], unique=False)
    op.create_index(op.f("ix_functional_nodes_functional_complexity"), "functional_nodes", ["functional_complexity"], unique=False)
    op.create_index(op.f("ix_functional_nodes_crawl_status"), "functional_nodes", ["crawl_status"], unique=False)
    op.create_index(op.f("ix_functional_nodes_mirror_status"), "functional_nodes", ["mirror_status"], unique=False)
    op.create_index(op.f("ix_functional_nodes_cutover_status"), "functional_nodes", ["cutover_status"], unique=False)
    op.create_index(op.f("ix_functional_nodes_priority_tier"), "functional_nodes", ["priority_tier"], unique=False)
    op.create_index(op.f("ix_functional_nodes_is_published"), "functional_nodes", ["is_published"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "functional_nodes" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_functional_nodes_is_published"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_priority_tier"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_cutover_status"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_mirror_status"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_crawl_status"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_functional_complexity"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_content_category"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_node_type"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_canonical_path"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_source_path"), table_name="functional_nodes")
    op.drop_index(op.f("ix_functional_nodes_legacy_node_id"), table_name="functional_nodes")
    op.drop_table("functional_nodes")
