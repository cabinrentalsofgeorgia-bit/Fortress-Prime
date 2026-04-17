"""merge_emergency_schema_fix_into_quote_chain

Revision ID: 0de35771a5b6
Revises: j5e6f7a8b9c0, 4757badd7918
Create Date: 2026-04-12 08:18:01.458612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0de35771a5b6'
down_revision: Union[str, Sequence[str], None] = ('j5e6f7a8b9c0', '4757badd7918')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
