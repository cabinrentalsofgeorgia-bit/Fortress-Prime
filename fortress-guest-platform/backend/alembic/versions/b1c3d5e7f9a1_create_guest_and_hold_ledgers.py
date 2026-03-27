"""create guest and hold ledgers

Revision ID: b1c3d5e7f9a1
Revises: a7b2c4d8e9f1
Create Date: 2026-03-22 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b1c3d5e7f9a1"
down_revision: Union[str, None] = "a7b2c4d8e9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "guests" not in tables:
        op.create_table(
            "guests",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=100), nullable=False),
            sa.Column("last_name", sa.String(length=100), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=True),
            sa.Column(
                "verification_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'unverified'"),
            ),
            sa.Column(
                "loyalty_tier",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'bronze'"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email", name="uq_guests_email"),
        )
        op.create_index("ix_guests_email", "guests", ["email"], unique=False)
        op.create_index("ix_guests_phone", "guests", ["phone"], unique=False)
        op.create_index("ix_guests_verification_status", "guests", ["verification_status"], unique=False)
        op.create_index("ix_guests_loyalty_tier", "guests", ["loyalty_tier"], unique=False)
        bind.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE guests TO fortress_api"))

    if "reservation_holds" not in tables and "properties" in tables:
        op.create_table(
            "reservation_holds",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("session_id", sa.String(length=255), nullable=False),
            sa.Column("check_in_date", sa.Date(), nullable=False),
            sa.Column("check_out_date", sa.Date(), nullable=False),
            sa.Column(
                "expires_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=50),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column(
                "num_guests",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("amount_total", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("quote_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("payment_intent_id", sa.String(length=255), nullable=True),
            sa.Column("special_requests", sa.Text(), nullable=True),
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
                "status IN ('active', 'expired', 'converted')",
                name="ck_reservation_holds_status",
            ),
            sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="SET NULL"),
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
        op.create_index(
            "ix_reservation_holds_session_id",
            "reservation_holds",
            ["session_id"],
            unique=False,
        )
        bind.execute(
            sa.text(
                """
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
                """
            )
        )
        bind.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reservation_holds TO fortress_api"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "reservation_holds" in tables:
        bind.execute(
            sa.text(
                "ALTER TABLE reservation_holds DROP CONSTRAINT IF EXISTS reservation_holds_no_overlap_active"
            )
        )
        op.drop_index("ix_reservation_holds_session_id", table_name="reservation_holds")
        op.drop_index("ix_reservation_holds_payment_intent_id", table_name="reservation_holds")
        op.drop_index("ix_reservation_holds_status_expires", table_name="reservation_holds")
        op.drop_index("ix_reservation_holds_property_dates", table_name="reservation_holds")
        op.drop_table("reservation_holds")

    if "guests" in tables:
        op.drop_index("ix_guests_loyalty_tier", table_name="guests")
        op.drop_index("ix_guests_verification_status", table_name="guests")
        op.drop_index("ix_guests_phone", table_name="guests")
        op.drop_index("ix_guests_email", table_name="guests")
        op.drop_table("guests")
