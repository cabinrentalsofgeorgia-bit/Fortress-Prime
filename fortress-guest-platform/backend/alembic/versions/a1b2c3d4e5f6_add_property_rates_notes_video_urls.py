"""add property rates_notes and video_urls columns

Revision ID: a1b2c3d4e5f6
Revises: f9b2c3d4e5a6
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "a1b2c3d4e5f6"
down_revision = "f9b2c3d4e5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("rates_notes", sa.Text(), nullable=True))
    op.add_column("properties", sa.Column("video_urls", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "video_urls")
    op.drop_column("properties", "rates_notes")
