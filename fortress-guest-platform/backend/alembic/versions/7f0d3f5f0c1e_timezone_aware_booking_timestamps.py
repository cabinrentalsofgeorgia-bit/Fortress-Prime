"""timezone-aware booking timestamps

Revision ID: 7f0d3f5f0c1e
Revises: c4a8f1e2b9d0
Create Date: 2026-03-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f0d3f5f0c1e"
down_revision: Union[str, None] = "c4a8f1e2b9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservation_holds" not in tables or "reservations" not in tables:
        return

    op.drop_constraint("ck_reservation_holds_status", "reservation_holds", type_="check")
    op.execute(
        sa.text(
            "UPDATE reservation_holds SET status = 'confirmed' WHERE status = 'converted'"
        )
    )
    op.create_check_constraint(
        "ck_reservation_holds_status",
        "reservation_holds",
        "status IN ('active', 'confirmed', 'expired', 'released')",
    )

    op.alter_column(
        "reservation_holds",
        "expires_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservation_holds",
        "created_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservation_holds",
        "updated_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    op.alter_column(
        "reservations",
        "access_code_valid_from",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="access_code_valid_from AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "access_code_valid_until",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="access_code_valid_until AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "security_deposit_updated_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="security_deposit_updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "created_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "updated_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservation_holds" not in tables or "reservations" not in tables:
        return

    op.alter_column(
        "reservations",
        "updated_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "created_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "security_deposit_updated_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="security_deposit_updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "access_code_valid_until",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="access_code_valid_until AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservations",
        "access_code_valid_from",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="access_code_valid_from AT TIME ZONE 'UTC'",
    )

    op.alter_column(
        "reservation_holds",
        "updated_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservation_holds",
        "created_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "reservation_holds",
        "expires_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )

    op.drop_constraint("ck_reservation_holds_status", "reservation_holds", type_="check")
    op.execute(
        sa.text(
            "UPDATE reservation_holds SET status = 'converted' WHERE status = 'confirmed'"
        )
    )
    op.create_check_constraint(
        "ck_reservation_holds_status",
        "reservation_holds",
        "status IN ('active', 'converted', 'expired', 'released')",
    )
