"""reservation holds and overlap exclusion constraints

Revision ID: c4a8f1e2b9d0
Revises: 8029df49b834
Create Date: 2026-03-20 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4a8f1e2b9d0"
down_revision: Union[str, None] = "8029df49b834"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "guests" not in tables or "reservations" not in tables or "properties" not in tables:
        return

    if "reservation_holds" not in tables:
        op.create_table(
            "reservation_holds",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("check_in_date", sa.Date(), nullable=False),
            sa.Column("check_out_date", sa.Date(), nullable=False),
            sa.Column("num_guests", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("amount_total", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("quote_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("payment_intent_id", sa.String(length=255), nullable=True),
            sa.Column("special_requests", sa.Text(), nullable=True),
            sa.Column(
                "expires_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint("check_out_date > check_in_date", name="ck_reservation_holds_date_order"),
            sa.CheckConstraint(
                "status IN ('active', 'confirmed', 'expired', 'released')",
                name="ck_reservation_holds_status",
            ),
            sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_reservation_holds_property_dates",
            "reservation_holds",
            ["property_id", "check_in_date", "check_out_date"],
            unique=False,
        )
        op.create_index(
            "ix_reservation_holds_status_expires",
            "reservation_holds",
            ["status", "expires_at"],
            unique=False,
        )
        op.create_index(
            "ix_reservation_holds_payment_intent_id",
            "reservation_holds",
            ["payment_intent_id"],
            unique=False,
        )

    # Partial exclusion: no two active holds may overlap on the same property.
    bind.execute(
        sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'reservation_holds_no_overlap_active'
                ) THEN
                    ALTER TABLE reservation_holds
                    ADD CONSTRAINT reservation_holds_no_overlap_active
                    EXCLUDE USING gist (
                        property_id WITH =,
                        daterange(check_in_date, check_out_date, '[)') WITH &&
                    )
                    WHERE (status = 'active');
                END IF;
            END $$;
        """)
    )

    # Exclusion: no two occupying reservations may overlap on the same property.
    bind.execute(
        sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'reservations_no_overlap_occupying'
                ) THEN
                    ALTER TABLE reservations
                    ADD CONSTRAINT reservations_no_overlap_occupying
                    EXCLUDE USING gist (
                        property_id WITH =,
                        daterange(check_in_date, check_out_date, '[)') WITH &&
                    )
                    WHERE (status IN ('confirmed', 'checked_in', 'pending_payment'));
                END IF;
            END $$;
        """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservation_holds" not in tables or "reservations" not in tables:
        return

    bind.execute(
        sa.text(
            "ALTER TABLE reservation_holds DROP CONSTRAINT IF EXISTS reservation_holds_no_overlap_active"
        )
    )
    bind.execute(
        sa.text(
            "ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservations_no_overlap_occupying"
        )
    )
    op.drop_index("ix_reservation_holds_payment_intent_id", table_name="reservation_holds")
    op.drop_index("ix_reservation_holds_status_expires", table_name="reservation_holds")
    op.drop_index("ix_reservation_holds_property_dates", table_name="reservation_holds")
    op.drop_table("reservation_holds")
