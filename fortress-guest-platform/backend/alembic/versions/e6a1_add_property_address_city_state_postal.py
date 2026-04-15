"""Phase E.6 — add city, state, postal_code to properties.

The properties table previously stored only the street address in the `address`
column. Phase E.6 adds the remaining components so the PDF renderer can assemble
a full one-line address (e.g. "12755 Aska Rd. Blue Ridge GA 30513") without calling
Streamline at render time. All three columns are nullable; backfilled by
backfill_property_data_from_streamline().

Revision ID: e6a1b2c3d4f5
Revises: e5b2c3d4e5f6
Create Date: 2026-04-14
"""
from __future__ import annotations

revision = "e6a1b2c3d4f5"
down_revision = "e5b2c3d4e5f6"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("properties", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("properties", sa.Column("state", sa.String(50), nullable=True))
    op.add_column("properties", sa.Column("postal_code", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "postal_code")
    op.drop_column("properties", "state")
    op.drop_column("properties", "city")
