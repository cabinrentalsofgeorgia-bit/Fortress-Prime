"""add qdrant columns manually

Revision ID: 54178bac45fe
Revises: 
Create Date: 2026-02-22 16:16:57.704116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54178bac45fe'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('qdrant_point_id', sa.UUID(), nullable=True))
    op.add_column('reservations', sa.Column('qdrant_point_id', sa.UUID(), nullable=True))
    op.add_column('work_orders', sa.Column('qdrant_point_id', sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column('work_orders', 'qdrant_point_id')
    op.drop_column('reservations', 'qdrant_point_id')
    op.drop_column('properties', 'qdrant_point_id')
