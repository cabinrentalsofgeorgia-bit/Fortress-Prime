"""harden hunter_queue session_fp upsert contract

Revision ID: 3a7d2c4f9b10
Revises: e1a4c9d7b2f3
Create Date: 2026-03-26 11:35:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3a7d2c4f9b10"
down_revision: Union[str, None] = "e1a4c9d7b2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "hunter_queue" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("hunter_queue")}
    if "session_fp" not in columns:
        op.add_column("hunter_queue", sa.Column("session_fp", sa.String(length=128), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE hunter_queue
               SET session_fp = COALESCE(NULLIF(payload->>'session_fp', ''), id::text)
             WHERE session_fp IS NULL OR session_fp = ''
            """
        )
    )
    op.alter_column(
        "hunter_queue",
        "session_fp",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_hunter_queue_session_fp "
            "ON hunter_queue (session_fp)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "hunter_queue" not in tables:
        return

    bind.execute(sa.text("DROP INDEX IF EXISTS uq_hunter_queue_session_fp"))
    columns = {column["name"] for column in inspector.get_columns("hunter_queue")}
    if "session_fp" in columns:
        op.drop_column("hunter_queue", "session_fp")
