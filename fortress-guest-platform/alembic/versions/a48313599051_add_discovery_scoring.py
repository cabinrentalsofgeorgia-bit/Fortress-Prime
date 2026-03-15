"""add_discovery_scoring

Revision ID: a48313599051
Revises: 9e35352c415a
Create Date: 2026-03-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a48313599051"
down_revision: Union[str, Sequence[str], None] = "9e35352c415a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "discovery_draft_items_v2",
        sa.Column("lethality_score", sa.Integer(), nullable=True),
        schema="legal",
    )
    op.add_column(
        "discovery_draft_items_v2",
        sa.Column("proportionality_score", sa.Integer(), nullable=True),
        schema="legal",
    )
    op.add_column(
        "discovery_draft_items_v2",
        sa.Column("correction_notes", sa.String(length=2000), nullable=True),
        schema="legal",
    )


def downgrade() -> None:
    op.drop_column("discovery_draft_items_v2", "correction_notes", schema="legal")
    op.drop_column("discovery_draft_items_v2", "proportionality_score", schema="legal")
    op.drop_column("discovery_draft_items_v2", "lethality_score", schema="legal")

