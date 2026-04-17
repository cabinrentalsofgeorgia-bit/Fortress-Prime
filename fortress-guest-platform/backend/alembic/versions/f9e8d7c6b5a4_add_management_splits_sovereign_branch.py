"""Add management_splits on sovereign branch (revenue_consumer dependency).

Revision ID: f9e8d7c6b5a4
Revises: f8e9d0c1b2a3
Create Date: 2026-04-04

``d1f4e8c2b7a9`` creates this table on a parallel Alembic branch; current head
``f8e9d0c1b2a3`` does not include it. The revenue consumer queries
``management_splits`` before journaling; without this table, processing fails.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f9e8d7c6b5a4"
down_revision: Union[str, Sequence[str], None] = "f8e9d0c1b2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_splits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("owner_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("pm_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", name="uq_management_splits_property_id"),
    )
    op.create_index("ix_management_splits_property_id", "management_splits", ["property_id"], unique=False)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON management_splits TO fortress_api")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE management_splits_id_seq TO fortress_api")


def downgrade() -> None:
    op.drop_index("ix_management_splits_property_id", table_name="management_splits")
    op.drop_table("management_splits")
