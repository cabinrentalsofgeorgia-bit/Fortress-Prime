"""add roles to staff users

Revision ID: c9d1e4f7a2b5
Revises: bc39f7e1a442
Create Date: 2026-03-22 12:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d1e4f7a2b5"
down_revision: Union[str, None] = "bc39f7e1a442"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_CHECK_CONSTRAINT = "ck_staff_users_role_valid"


def _check_constraints(bind: sa.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "staff_users" not in tables:
        return

    op.execute(sa.text("UPDATE staff_users SET role = 'super_admin' WHERE role IS NULL OR role <> 'super_admin'"))
    op.alter_column(
        "staff_users",
        "role",
        existing_type=sa.String(length=50),
        type_=sa.String(length=50),
        existing_nullable=False,
        server_default="super_admin",
    )

    if ROLE_CHECK_CONSTRAINT not in _check_constraints(bind, "staff_users"):
        op.create_check_constraint(
            ROLE_CHECK_CONSTRAINT,
            "staff_users",
            "role IN ('super_admin', 'manager', 'reviewer')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "staff_users" not in tables:
        return

    if ROLE_CHECK_CONSTRAINT in _check_constraints(bind, "staff_users"):
        op.drop_constraint(ROLE_CHECK_CONSTRAINT, "staff_users", type_="check")

    op.execute(sa.text("UPDATE staff_users SET role = 'staff'"))
    op.alter_column(
        "staff_users",
        "role",
        existing_type=sa.String(length=50),
        type_=sa.String(length=50),
        existing_nullable=False,
        server_default="staff",
    )
