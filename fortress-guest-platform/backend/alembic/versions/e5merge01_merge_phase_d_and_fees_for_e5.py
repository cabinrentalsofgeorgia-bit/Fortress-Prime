"""merge_phase_d_and_fees_for_e5

Revision ID: e5merge01
Revises: f1e2d3c4b5a6, k6f7a8b9c0d1
Create Date: 2026-04-14 16:20:38.368155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5merge01'
down_revision: Union[str, Sequence[str], None] = ('f1e2d3c4b5a6', 'k6f7a8b9c0d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
