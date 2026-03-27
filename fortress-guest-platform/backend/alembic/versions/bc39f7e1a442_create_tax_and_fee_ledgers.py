"""create tax and fee ledgers

Revision ID: bc39f7e1a442
Revises: aa21c6e7d911
Create Date: 2026-03-22 10:05:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bc39f7e1a442"
down_revision: Union[str, None] = "aa21c6e7d911"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "taxes" not in tables:
        op.create_table(
            "taxes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("percentage_rate", sa.Numeric(6, 2), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_taxes_name", "taxes", ["name"], unique=True)

    if "fees" not in tables:
        op.create_table(
            "fees",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("flat_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("is_pet_fee", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_fees_name", "fees", ["name"], unique=True)

    if "property_taxes" not in tables:
        op.create_table(
            "property_taxes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tax_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("property_id", "tax_id", name="uq_property_taxes_property_tax"),
        )
        op.create_index("ix_property_taxes_property_id", "property_taxes", ["property_id"], unique=False)

    if "property_fees" not in tables:
        op.create_table(
            "property_fees",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("fee_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["fee_id"], ["fees.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("property_id", "fee_id", name="uq_property_fees_property_fee"),
        )
        op.create_index("ix_property_fees_property_id", "property_fees", ["property_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_property_fees_property_id", table_name="property_fees")
    op.drop_table("property_fees")
    op.drop_index("ix_property_taxes_property_id", table_name="property_taxes")
    op.drop_table("property_taxes")
    op.drop_index("ix_fees_name", table_name="fees")
    op.drop_table("fees")
    op.drop_index("ix_taxes_name", table_name="taxes")
    op.drop_table("taxes")
