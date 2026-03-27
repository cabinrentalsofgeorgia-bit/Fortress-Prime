"""add property availability cache column

Revision ID: c1a9d7e4f2b3
Revises: b8e1d4f7c2a3
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1a9d7e4f2b3"
down_revision: Union[str, None] = "b8e1d4f7c2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "availability" not in columns:
        op.add_column(
            "properties",
            sa.Column("availability", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "availability" in columns:
        op.drop_column("properties", "availability")
