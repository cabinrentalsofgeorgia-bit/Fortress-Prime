"""create property_stay_restrictions table (Strike 18 yield saturation)

Revision ID: e4b2c8f1a9d0
Revises: d8a1f3e9c2b0
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e4b2c8f1a9d0"
down_revision: Union[str, None] = "d8a1f3e9c2b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables or "property_stay_restrictions" in tables:
        return

    op.create_table(
        "property_stay_restrictions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_blackout", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("must_check_in_on_day", sa.SmallInteger(), nullable=True),
        sa.Column("must_check_out_on_day", sa.SmallInteger(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'sovereign'"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("end_date >= start_date", name="ck_property_stay_restrictions_date_order"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_property_stay_restrictions_property_id",
        "property_stay_restrictions",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "ix_property_stay_restrictions_property_dates",
        "property_stay_restrictions",
        ["property_id", "start_date", "end_date"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "property_stay_restrictions" not in inspector.get_table_names():
        return
    op.drop_index("ix_property_stay_restrictions_property_dates", table_name="property_stay_restrictions")
    op.drop_index("ix_property_stay_restrictions_property_id", table_name="property_stay_restrictions")
    op.drop_table("property_stay_restrictions")
