"""add blocked_days table for calendar persistence

Revision ID: c19a8bb64d50
Revises: 85f6b0980cdc
Create Date: 2026-02-24 10:00:07.794728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c19a8bb64d50'
down_revision: Union[str, Sequence[str], None] = '85f6b0980cdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'blocked_days',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('block_type', sa.String(length=50), nullable=True),
        sa.Column('confirmation_code', sa.String(length=50), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'property_id', 'start_date', 'end_date', 'block_type',
            name='uq_blocked_days_prop_dates_type',
        ),
    )
    op.create_index(op.f('ix_blocked_days_property_id'), 'blocked_days', ['property_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_blocked_days_property_id'), table_name='blocked_days')
    op.drop_table('blocked_days')
