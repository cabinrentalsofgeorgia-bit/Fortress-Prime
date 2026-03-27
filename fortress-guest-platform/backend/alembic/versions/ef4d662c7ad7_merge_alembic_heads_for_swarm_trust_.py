"""merge alembic heads for swarm trust governance

Revision ID: ef4d662c7ad7
Revises: 2c5f4a8e1b7d, 7f0d3f5f0c1e, c6b1f2e4a9d8
Create Date: 2026-03-22 17:03:45.471633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef4d662c7ad7'
down_revision: Union[str, Sequence[str], None] = ('2c5f4a8e1b7d', '7f0d3f5f0c1e', 'c6b1f2e4a9d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
