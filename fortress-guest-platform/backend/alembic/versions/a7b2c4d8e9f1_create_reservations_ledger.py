"""create reservations ledger

Revision ID: a7b2c4d8e9f1
Revises: 9c1a7b6e5d4f
Create Date: 2026-03-22 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b2c4d8e9f1"
down_revision: Union[str, None] = "9c1a7b6e5d4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables or "reservations" in tables:
        return

    op.create_table(
        "reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "guest_email",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "guest_name",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("guest_phone", sa.String(length=50), nullable=True),
        sa.Column("confirmation_code", sa.String(length=50), nullable=True),
        sa.Column("check_in_date", sa.Date(), nullable=False),
        sa.Column("check_out_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "num_guests",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("num_adults", sa.Integer(), nullable=True),
        sa.Column("num_children", sa.Integer(), nullable=True),
        sa.Column(
            "num_pets",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("booking_source", sa.String(length=100), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("access_code", sa.String(length=20), nullable=True),
        sa.Column("access_code_valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_code_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("streamline_reservation_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("check_out_date > check_in_date", name="ck_reservations_date_order"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_code", name="uq_reservations_confirmation_code"),
    )
    op.create_index("ix_reservations_guest_email", "reservations", ["guest_email"], unique=False)
    op.create_index("ix_reservations_guest_id", "reservations", ["guest_id"], unique=False)
    op.create_index("ix_reservations_check_in_date", "reservations", ["check_in_date"], unique=False)
    op.create_index("ix_reservations_check_out_date", "reservations", ["check_out_date"], unique=False)
    op.create_index("ix_reservations_status", "reservations", ["status"], unique=False)
    op.create_index(
        "ix_reservations_property_dates",
        "reservations",
        ["property_id", "check_in_date", "check_out_date"],
        unique=False,
    )
    bind.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reservations TO fortress_api"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservations" not in tables:
        return

    op.drop_index("ix_reservations_property_dates", table_name="reservations")
    op.drop_index("ix_reservations_status", table_name="reservations")
    op.drop_index("ix_reservations_check_out_date", table_name="reservations")
    op.drop_index("ix_reservations_check_in_date", table_name="reservations")
    op.drop_index("ix_reservations_guest_id", table_name="reservations")
    op.drop_index("ix_reservations_guest_email", table_name="reservations")
    op.drop_table("reservations")
