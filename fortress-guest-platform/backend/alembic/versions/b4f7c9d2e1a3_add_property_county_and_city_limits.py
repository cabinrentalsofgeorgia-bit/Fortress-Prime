"""add property county and city_limits columns

Revision ID: b4f7c9d2e1a3
Revises: None (standalone — apply to all target databases)
Create Date: 2026-04-03

This migration ensures the properties table has the county and city_limits
columns required by the FinTech Ledger (Level 62) for county-specific tax
calculations. The county column may already exist on some databases; this
migration is idempotent.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "b4f7c9d2e1a3"
down_revision = None
branch_labels = ("property_tax_geo",)
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("properties", "county"):
        op.add_column("properties", sa.Column("county", sa.String(100), nullable=True))
        op.execute("UPDATE properties SET county = 'Fannin' WHERE county IS NULL")

    if not _column_exists("properties", "city_limits"):
        op.add_column(
            "properties",
            sa.Column("city_limits", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    if _column_exists("properties", "city_limits"):
        op.drop_column("properties", "city_limits")
    if _column_exists("properties", "county"):
        op.drop_column("properties", "county")
