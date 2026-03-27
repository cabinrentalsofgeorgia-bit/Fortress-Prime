"""create staff_users in sovereign db

Revision ID: 6f2c1b4a9d77
Revises: 5b3f7d9c2a10
Create Date: 2026-03-21 23:35:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6f2c1b4a9d77"
down_revision: Union[str, None] = "5b3f7d9c2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names(bind: sa.Connection) -> set[str]:
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    if "staff_users" not in tables:
        op.create_table(
            "staff_users",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=100), nullable=False),
            sa.Column("last_name", sa.String(length=100), nullable=False),
            sa.Column("role", sa.String(length=50), nullable=False, server_default="staff"),
            sa.Column(
                "permissions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_login_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("notification_phone", sa.String(length=20), nullable=True),
            sa.Column("notification_email", sa.String(length=255), nullable=True),
            sa.Column("notify_urgent", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notify_workorders", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id", name="staff_users_pkey"),
            sa.UniqueConstraint("email", name="uq_staff_users_email"),
        )

    index_names = _index_names(bind, "staff_users")
    if "ix_staff_users_email" not in index_names:
        op.create_index("ix_staff_users_email", "staff_users", ["email"], unique=False)
    if "ix_staff_users_role" not in index_names:
        op.create_index("ix_staff_users_role", "staff_users", ["role"], unique=False)

    bind.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE staff_users TO fortress_api"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "staff_users" not in tables:
        return

    index_names = _index_names(bind, "staff_users")
    if "ix_staff_users_role" in index_names:
        op.drop_index("ix_staff_users_role", table_name="staff_users")
    if "ix_staff_users_email" in index_names:
        op.drop_index("ix_staff_users_email", table_name="staff_users")

    op.drop_table("staff_users")
