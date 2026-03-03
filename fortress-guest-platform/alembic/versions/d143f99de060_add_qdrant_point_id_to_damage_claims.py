"""add qdrant_point_id to damage_claims

Revision ID: d143f99de060
Revises: d40bfe5fabd2
Create Date: 2026-02-23 09:32:45.971958

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd143f99de060'
down_revision: Union[str, Sequence[str], None] = 'd40bfe5fabd2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('damage_claims', sa.Column('qdrant_point_id', sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column('damage_claims', 'qdrant_point_id')
