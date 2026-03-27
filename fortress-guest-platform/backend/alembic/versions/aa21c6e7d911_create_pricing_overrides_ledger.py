"""create pricing overrides ledger

Revision ID: aa21c6e7d911
Revises: f3d6a1b8c9e2
Create Date: 2026-03-22 09:45:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "aa21c6e7d911"
down_revision: Union[str, None] = "f3d6a1b8c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "pricing_overrides" not in tables:
        op.create_table(
            "pricing_overrides",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("adjustment_percentage", sa.Numeric(6, 2), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=False),
            sa.Column("approved_by", sa.String(length=255), nullable=False),
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
            sa.CheckConstraint("end_date >= start_date", name="ck_pricing_overrides_date_order"),
            sa.CheckConstraint(
                "adjustment_percentage >= -100.00 AND adjustment_percentage <= 100.00",
                name="ck_pricing_overrides_adjustment_range",
            ),
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("pricing_overrides")}
    if "ix_pricing_overrides_property_id" not in indexes:
        op.create_index(
            "ix_pricing_overrides_property_id",
            "pricing_overrides",
            ["property_id"],
            unique=False,
        )
    if "ix_pricing_overrides_property_dates" not in indexes:
        op.create_index(
            "ix_pricing_overrides_property_dates",
            "pricing_overrides",
            ["property_id", "start_date", "end_date"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_pricing_overrides_property_dates", table_name="pricing_overrides")
    op.drop_index("ix_pricing_overrides_property_id", table_name="pricing_overrides")
    op.drop_table("pricing_overrides")
