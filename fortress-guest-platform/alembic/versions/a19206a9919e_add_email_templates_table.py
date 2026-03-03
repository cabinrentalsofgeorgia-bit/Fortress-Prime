"""add email_templates table

Revision ID: a19206a9919e
Revises: cd8eee1d09b1
Create Date: 2026-02-24 12:49:46.490428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect as sa_inspect

revision: str = 'a19206a9919e'
down_revision: Union[str, Sequence[str], None] = 'cd8eee1d09b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if 'email_templates' not in inspector.get_table_names():
        op.create_table(
            'email_templates',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('trigger_event', sa.String(length=100), nullable=False),
            sa.Column('subject_template', sa.String(length=1000), nullable=False, server_default=''),
            sa.Column('body_template', sa.Text(), nullable=False, server_default=''),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_templates_name'), 'email_templates', ['name'], unique=False)
        op.create_index(op.f('ix_email_templates_trigger_event'), 'email_templates', ['trigger_event'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_templates_trigger_event'), table_name='email_templates')
    op.drop_index(op.f('ix_email_templates_name'), table_name='email_templates')
    op.drop_table('email_templates')
