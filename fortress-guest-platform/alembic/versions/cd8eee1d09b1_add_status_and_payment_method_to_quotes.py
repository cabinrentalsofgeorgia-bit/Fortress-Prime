"""add status and payment_method to quotes

Revision ID: cd8eee1d09b1
Revises: c19a8bb64d50
Create Date: 2026-02-24 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cd8eee1d09b1'
down_revision: Union[str, Sequence[str], None] = 'c19a8bb64d50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quotes', sa.Column('status', sa.String(length=20), nullable=True))
    op.add_column('quotes', sa.Column('payment_method', sa.String(length=20), nullable=True))
    op.execute("UPDATE quotes SET status = 'draft' WHERE status IS NULL")
    op.alter_column('quotes', 'status', nullable=False, server_default='draft')
    op.create_index(op.f('ix_quotes_status'), 'quotes', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quotes_status'), table_name='quotes')
    op.drop_column('quotes', 'payment_method')
    op.drop_column('quotes', 'status')
