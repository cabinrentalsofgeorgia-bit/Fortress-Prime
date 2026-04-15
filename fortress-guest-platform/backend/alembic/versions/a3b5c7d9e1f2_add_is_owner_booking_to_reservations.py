"""add_is_owner_booking_to_reservations

Phase B: adds is_owner_booking BOOLEAN NOT NULL DEFAULT false to the
reservations table so owner-stay bookings (Streamline maketype_name = 'O')
can be explicitly flagged and excluded from statement computation.

Revision ID: a3b5c7d9e1f2
Revises: f8e1d2c3b4a5
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b5c7d9e1f2"
down_revision: Union[str, Sequence[str], None] = "f8e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE reservations
            ADD COLUMN is_owner_booking BOOLEAN NOT NULL DEFAULT false
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_reservations_is_owner_booking "
        "ON reservations (is_owner_booking)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_reservations_is_owner_booking"))
    op.execute(sa.text(
        "ALTER TABLE reservations DROP COLUMN IF EXISTS is_owner_booking"
    ))
