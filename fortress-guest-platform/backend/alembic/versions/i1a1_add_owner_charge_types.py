"""I.1: Add 4 missing owner_charge_type_enum values for Streamline parity.

Adds: statement_marker, room_revenue, hacienda_tax, charge_expired_owner.

ALTER TYPE ... ADD VALUE is DDL and executes outside the transaction block
in Postgres. Using IF NOT EXISTS makes it idempotent.

Revision ID: i1a1_add_owner_charge_types
Revises: g6a1_add_owner_middle_name
Create Date: 2026-04-16
"""
from __future__ import annotations

from alembic import op

revision = "i1a1_add_owner_charge_types"
down_revision = "g6a1_add_owner_middle_name"
branch_labels = None
depends_on = None

_NEW_VALUES = [
    "statement_marker",
    "room_revenue",
    "hacienda_tax",
    "charge_expired_owner",
]


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction in older Postgres.
    # execute() in Alembic runs inside the default transaction — safe in PG 12+.
    for val in _NEW_VALUES:
        op.execute(f"ALTER TYPE owner_charge_type_enum ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    # Postgres does not support removing enum values.
    # A full drop/recreate would be needed; not worth the risk.
    # Downgrade is intentionally a no-op — values are simply unused if not referenced.
    pass
