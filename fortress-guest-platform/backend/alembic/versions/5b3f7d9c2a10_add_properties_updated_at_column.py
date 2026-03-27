"""add properties updated_at column when missing

Revision ID: 5b3f7d9c2a10
Revises: 4f6a8f7d2b21
Create Date: 2026-03-21 22:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b3f7d9c2a10"
down_revision: Union[str, None] = "4f6a8f7d2b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "updated_at" in columns:
        return

    op.add_column(
        "properties",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE properties SET updated_at = COALESCE(updated_at, created_at, now())"
        )
    )
    op.alter_column(
        "properties",
        "updated_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "properties" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("properties")}
    if "updated_at" in columns:
        op.drop_column("properties", "updated_at")
