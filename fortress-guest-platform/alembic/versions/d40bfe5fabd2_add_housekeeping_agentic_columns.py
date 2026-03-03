"""add housekeeping agentic columns

Revision ID: d40bfe5fabd2
Revises: 54178bac45fe
Create Date: 2026-02-22 21:56:28.423200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd40bfe5fabd2'
down_revision: Union[str, Sequence[str], None] = '54178bac45fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # properties — housekeeping defaults
    op.add_column('properties', sa.Column('default_housekeeper_id', sa.UUID(), nullable=True))
    op.add_column('properties', sa.Column('default_clean_minutes', sa.Integer(), nullable=True))
    op.add_column('properties', sa.Column('streamline_checklist_id', sa.String(100), nullable=True))
    op.create_foreign_key(
        'fk_properties_default_housekeeper',
        'properties', 'staff_users',
        ['default_housekeeper_id'], ['id'],
        ondelete='SET NULL',
    )

    # housekeeping_tasks — agentic dispatch
    op.add_column('housekeeping_tasks', sa.Column('streamline_checklist_id', sa.String(100), nullable=True))
    op.add_column('housekeeping_tasks', sa.Column('dispatched_by', sa.String(50), nullable=True))
    op.add_column('housekeeping_tasks', sa.Column('dispatch_payload', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('housekeeping_tasks', 'dispatch_payload')
    op.drop_column('housekeeping_tasks', 'dispatched_by')
    op.drop_column('housekeeping_tasks', 'streamline_checklist_id')
    op.drop_constraint('fk_properties_default_housekeeper', 'properties', type_='foreignkey')
    op.drop_column('properties', 'streamline_checklist_id')
    op.drop_column('properties', 'default_clean_minutes')
    op.drop_column('properties', 'default_housekeeper_id')
