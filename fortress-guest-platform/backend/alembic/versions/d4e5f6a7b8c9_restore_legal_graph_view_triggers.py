"""restore legal graph view triggers

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-30 22:55:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_nodes_view_write ON legal.case_graph_nodes"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_case_graph_nodes_view_write
            INSTEAD OF INSERT OR DELETE ON legal.case_graph_nodes
            FOR EACH ROW EXECUTE FUNCTION legal.case_graph_nodes_view_write()
            """
        )
    )

    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_edges_view_write ON legal.case_graph_edges"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_case_graph_edges_view_write
            INSTEAD OF INSERT OR DELETE ON legal.case_graph_edges
            FOR EACH ROW EXECUTE FUNCTION legal.case_graph_edges_view_write()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_edges_view_write ON legal.case_graph_edges"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_case_graph_nodes_view_write ON legal.case_graph_nodes"))
