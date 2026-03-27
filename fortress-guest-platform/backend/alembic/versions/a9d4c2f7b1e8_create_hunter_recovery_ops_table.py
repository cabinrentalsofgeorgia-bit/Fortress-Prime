"""create hunter_recovery_ops table

Revision ID: a9d4c2f7b1e8
Revises: 3a7d2c4f9b10
Create Date: 2026-03-26 12:15:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9d4c2f7b1e8"
down_revision: Union[str, Sequence[str], None] = "3a7d2c4f9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


hunter_recovery_op_status = postgresql.ENUM(
    "QUEUED",
    "EXECUTING",
    "DRAFT_READY",
    "DISPATCHED",
    "REJECTED",
    name="hunter_recovery_op_status",
)
hunter_recovery_op_status_column = postgresql.ENUM(
    "QUEUED",
    "EXECUTING",
    "DRAFT_READY",
    "DISPATCHED",
    "REJECTED",
    name="hunter_recovery_op_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hunter_recovery_ops" in inspector.get_table_names():
        return

    hunter_recovery_op_status.create(bind, checkfirst=True)
    op.create_table(
        "hunter_recovery_ops",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cart_id", sa.String(length=255), nullable=False),
        sa.Column("guest_name", sa.String(length=255), nullable=True),
        sa.Column("cabin_name", sa.String(length=255), nullable=True),
        sa.Column("cart_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("status", hunter_recovery_op_status_column, server_default="QUEUED", nullable=False),
        sa.Column("ai_draft_body", sa.Text(), nullable=True),
        sa.Column("assigned_worker", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hunter_recovery_ops_cart_id"), "hunter_recovery_ops", ["cart_id"], unique=False)
    op.create_index(op.f("ix_hunter_recovery_ops_status"), "hunter_recovery_ops", ["status"], unique=False)
    op.create_index("ix_hunter_recovery_ops_status_created", "hunter_recovery_ops", ["status", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hunter_recovery_ops" not in inspector.get_table_names():
        hunter_recovery_op_status.drop(bind, checkfirst=True)
        return

    op.drop_index("ix_hunter_recovery_ops_status_created", table_name="hunter_recovery_ops")
    op.drop_index(op.f("ix_hunter_recovery_ops_status"), table_name="hunter_recovery_ops")
    op.drop_index(op.f("ix_hunter_recovery_ops_cart_id"), table_name="hunter_recovery_ops")
    op.drop_table("hunter_recovery_ops")
    hunter_recovery_op_status.drop(bind, checkfirst=True)
