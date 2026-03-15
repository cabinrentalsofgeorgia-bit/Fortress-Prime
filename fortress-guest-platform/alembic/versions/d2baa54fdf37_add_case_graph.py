"""add_case_graph

Revision ID: d2baa54fdf37
Revises: cf71c23e42d2
Create Date: 2026-03-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d2baa54fdf37"
down_revision: Union[str, Sequence[str], None] = "cf71c23e42d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "case_graph_nodes_v2",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_slug", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_reference_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("properties_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index("ix_legal_case_graph_nodes_v2_case_slug", "case_graph_nodes_v2", ["case_slug"], unique=False, schema="legal")
    op.create_index("ix_legal_case_graph_nodes_v2_entity_reference_id", "case_graph_nodes_v2", ["entity_reference_id"], unique=False, schema="legal")
    op.create_index("ix_legal_case_graph_nodes_v2_entity_type", "case_graph_nodes_v2", ["entity_type"], unique=False, schema="legal")

    op.create_table(
        "case_graph_edges_v2",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_slug", sa.String(length=255), nullable=False),
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", sa.String(length=128), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("source_evidence_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["source_node_id"], ["legal.case_graph_nodes_v2.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["legal.case_graph_nodes_v2.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index("ix_legal_case_graph_edges_v2_case_slug", "case_graph_edges_v2", ["case_slug"], unique=False, schema="legal")
    op.create_index("ix_legal_case_graph_edges_v2_source_evidence_id", "case_graph_edges_v2", ["source_evidence_id"], unique=False, schema="legal")
    op.create_index("ix_legal_case_graph_edges_v2_source_node_id", "case_graph_edges_v2", ["source_node_id"], unique=False, schema="legal")
    op.create_index("ix_legal_case_graph_edges_v2_target_node_id", "case_graph_edges_v2", ["target_node_id"], unique=False, schema="legal")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_legal_case_graph_edges_v2_target_node_id", table_name="case_graph_edges_v2", schema="legal")
    op.drop_index("ix_legal_case_graph_edges_v2_source_node_id", table_name="case_graph_edges_v2", schema="legal")
    op.drop_index("ix_legal_case_graph_edges_v2_source_evidence_id", table_name="case_graph_edges_v2", schema="legal")
    op.drop_index("ix_legal_case_graph_edges_v2_case_slug", table_name="case_graph_edges_v2", schema="legal")
    op.drop_table("case_graph_edges_v2", schema="legal")

    op.drop_index("ix_legal_case_graph_nodes_v2_entity_type", table_name="case_graph_nodes_v2", schema="legal")
    op.drop_index("ix_legal_case_graph_nodes_v2_entity_reference_id", table_name="case_graph_nodes_v2", schema="legal")
    op.drop_index("ix_legal_case_graph_nodes_v2_case_slug", table_name="case_graph_nodes_v2", schema="legal")
    op.drop_table("case_graph_nodes_v2", schema="legal")

