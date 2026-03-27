"""add property ota metadata column when missing

Revision ID: c8f1a2d4e6b7
Revises: ab24c6d8e1f0
Create Date: 2026-03-24 22:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c8f1a2d4e6b7"
down_revision: Union[str, Sequence[str], None] = "ab24c6d8e1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "ota_metadata" in columns:
        return

    op.add_column(
        "properties",
        sa.Column(
            "ota_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "ota_metadata" in columns:
        op.drop_column("properties", "ota_metadata")
