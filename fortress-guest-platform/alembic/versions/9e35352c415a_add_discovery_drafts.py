"""add_discovery_drafts

Revision ID: 9e35352c415a
Revises: d2baa54fdf37
Create Date: 2026-03-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9e35352c415a"
down_revision: Union[str, Sequence[str], None] = "d2baa54fdf37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovery_draft_packs_v2",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_slug", sa.String(length=255), nullable=False),
        sa.Column("target_entity", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index(
        "ix_legal_discovery_draft_packs_v2_case_slug",
        "discovery_draft_packs_v2",
        ["case_slug"],
        unique=False,
        schema="legal",
    )
    op.create_index(
        "ix_legal_discovery_draft_packs_v2_target_entity",
        "discovery_draft_packs_v2",
        ["target_entity"],
        unique=False,
        schema="legal",
    )
    op.create_index(
        "ix_legal_discovery_draft_packs_v2_status",
        "discovery_draft_packs_v2",
        ["status"],
        unique=False,
        schema="legal",
    )

    op.create_table(
        "discovery_draft_items_v2",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("rationale_from_graph", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pack_id"], ["legal.discovery_draft_packs_v2.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index(
        "ix_legal_discovery_draft_items_v2_pack_id",
        "discovery_draft_items_v2",
        ["pack_id"],
        unique=False,
        schema="legal",
    )
    op.create_index(
        "ix_legal_discovery_draft_items_v2_category",
        "discovery_draft_items_v2",
        ["category"],
        unique=False,
        schema="legal",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_legal_discovery_draft_items_v2_category",
        table_name="discovery_draft_items_v2",
        schema="legal",
    )
    op.drop_index(
        "ix_legal_discovery_draft_items_v2_pack_id",
        table_name="discovery_draft_items_v2",
        schema="legal",
    )
    op.drop_table("discovery_draft_items_v2", schema="legal")

    op.drop_index(
        "ix_legal_discovery_draft_packs_v2_status",
        table_name="discovery_draft_packs_v2",
        schema="legal",
    )
    op.drop_index(
        "ix_legal_discovery_draft_packs_v2_target_entity",
        table_name="discovery_draft_packs_v2",
        schema="legal",
    )
    op.drop_index(
        "ix_legal_discovery_draft_packs_v2_case_slug",
        table_name="discovery_draft_packs_v2",
        schema="legal",
    )
    op.drop_table("discovery_draft_packs_v2", schema="legal")

