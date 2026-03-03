"""add lead quote and quote_option models

Revision ID: 85f6b0980cdc
Revises: d143f99de060
Create Date: 2026-02-23 23:43:44.612963

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '85f6b0980cdc'
down_revision: Union[str, Sequence[str], None] = 'd143f99de060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create leads, quotes, and quote_options tables."""

    op.create_table(
        'leads',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('streamline_lead_id', sa.String(length=100), nullable=True),
        sa.Column('guest_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('guest_message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('ai_score', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('streamline_lead_id'),
    )
    op.create_index('ix_leads_streamline_lead_id', 'leads', ['streamline_lead_id'], unique=True)
    op.create_index('ix_leads_email', 'leads', ['email'], unique=False)
    op.create_index('ix_leads_status', 'leads', ['status'], unique=False)
    op.create_index('ix_leads_source', 'leads', ['source'], unique=False)

    op.create_table(
        'quotes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=False),
        sa.Column('expires_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_quotes_lead_id', 'quotes', ['lead_id'], unique=False)

    op.create_table(
        'quote_options',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('quote_id', sa.UUID(), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=False),
        sa.Column('check_in_date', sa.Date(), nullable=False),
        sa.Column('check_out_date', sa.Date(), nullable=False),
        sa.Column('base_rent', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('taxes', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('fees', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('total_price', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['quote_id'], ['quotes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_quote_options_quote_id', 'quote_options', ['quote_id'], unique=False)
    op.create_index('ix_quote_options_property_id', 'quote_options', ['property_id'], unique=False)


def downgrade() -> None:
    """Drop quote_options, quotes, and leads tables."""
    op.drop_index('ix_quote_options_property_id', table_name='quote_options')
    op.drop_index('ix_quote_options_quote_id', table_name='quote_options')
    op.drop_table('quote_options')

    op.drop_index('ix_quotes_lead_id', table_name='quotes')
    op.drop_table('quotes')

    op.drop_index('ix_leads_source', table_name='leads')
    op.drop_index('ix_leads_status', table_name='leads')
    op.drop_index('ix_leads_email', table_name='leads')
    op.drop_index('ix_leads_streamline_lead_id', table_name='leads')
    op.drop_table('leads')
