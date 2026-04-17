"""Add cleaning_fee to properties table for deterministic quote fee calculation.

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-04-12
"""
from __future__ import annotations

revision = "j5e6f7a8b9c0"
down_revision = "i4d5e6f7a8b9"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE properties ADD COLUMN IF NOT EXISTS cleaning_fee NUMERIC(10,2)"
    ))
    # Seed from historical reservation data — use the modal (most-frequent) cleaning
    # fee per property so the quote tool reflects real charges immediately.
    # Values sourced from fortress_guest.reservations canonical history.
    op.execute(sa.text("""
        UPDATE properties SET cleaning_fee = v.fee
        FROM (VALUES
            ('382651', 275.00),
            ('235641', 200.00),
            ('419022', 225.00),
            ('980130', 275.00),
            ('306758', 125.00),
            ('70206',  175.00),
            ('756771', 185.00),
            ('70209',  275.00),
            ('441334', 200.00),
            ('70220',  275.00),
            ('70222',  275.00),
            ('1001528',285.00),
            ('70224',  275.00)
        ) AS v(sl_id, fee)
        WHERE properties.streamline_property_id = v.sl_id
    """))
    op.execute(sa.text(
        "GRANT SELECT, UPDATE ON properties TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE properties DROP COLUMN IF EXISTS cleaning_fee"
    ))
