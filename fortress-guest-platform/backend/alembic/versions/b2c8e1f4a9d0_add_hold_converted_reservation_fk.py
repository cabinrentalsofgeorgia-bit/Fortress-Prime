"""Add converted_reservation_id to reservation_holds for idempotent finalization.

Revision ID: b2c8e1f4a9d0
Revises: 91b1e1b4c3d2
Create Date: 2026-03-23 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2c8e1f4a9d0"
down_revision: Union[str, Sequence[str], None] = "91b1e1b4c3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reservation_holds" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("reservation_holds")}
    if "converted_reservation_id" in cols:
        return
    op.add_column(
        "reservation_holds",
        sa.Column(
            "converted_reservation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_reservation_holds_converted_reservation_id",
        "reservation_holds",
        "reservations",
        ["converted_reservation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_reservation_holds_converted_reservation_id"),
        "reservation_holds",
        ["converted_reservation_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reservation_holds" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("reservation_holds")}
    if "converted_reservation_id" not in cols:
        return
    op.drop_index(op.f("ix_reservation_holds_converted_reservation_id"), table_name="reservation_holds")
    op.drop_constraint("fk_reservation_holds_converted_reservation_id", "reservation_holds", type_="foreignkey")
    op.drop_column("reservation_holds", "converted_reservation_id")
