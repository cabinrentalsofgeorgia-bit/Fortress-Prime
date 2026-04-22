"""Add has_attachments and image_descriptions to email_messages (Deployment C).

Revision ID: m8f9a0b1c2d3
Revises: l7e8f1a2b3c4
Create Date: 2026-04-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "m8f9a0b1c2d3"
down_revision = "l7e8f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_messages",
        sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "email_messages",
        sa.Column("image_descriptions", postgresql.JSONB(), nullable=True),
    )
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON email_messages TO fortress_api"))


def downgrade() -> None:
    op.drop_column("email_messages", "image_descriptions")
    op.drop_column("email_messages", "has_attachments")
