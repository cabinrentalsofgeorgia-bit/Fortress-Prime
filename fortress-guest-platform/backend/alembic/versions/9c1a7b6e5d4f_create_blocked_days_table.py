"""create blocked_days table

Revision ID: 9c1a7b6e5d4f
Revises: 6f2c1b4a9d77
Create Date: 2026-03-22 00:08:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9c1a7b6e5d4f"
down_revision: Union[str, None] = "6f2c1b4a9d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables or "blocked_days" in tables:
        return

    op.create_table(
        "blocked_days",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "block_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'reservation'"),
        ),
        sa.Column("confirmation_code", sa.String(length=50), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'streamline'"),
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
        sa.CheckConstraint("end_date > start_date", name="ck_blocked_days_date_order"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "property_id",
            "start_date",
            "end_date",
            "block_type",
            name="uq_blocked_days_prop_dates_type",
        ),
    )
    op.create_index("ix_blocked_days_property_id", "blocked_days", ["property_id"], unique=False)
    op.create_index(
        "ix_blocked_days_property_dates",
        "blocked_days",
        ["property_id", "start_date", "end_date"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "blocked_days" not in tables:
        return

    op.drop_index("ix_blocked_days_property_dates", table_name="blocked_days")
    op.drop_index("ix_blocked_days_property_id", table_name="blocked_days")
    op.drop_table("blocked_days")
