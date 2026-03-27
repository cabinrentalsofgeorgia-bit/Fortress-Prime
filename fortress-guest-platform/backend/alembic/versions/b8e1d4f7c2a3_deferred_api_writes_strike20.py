"""deferred_api_writes table and Strike 20 reconciliation columns

Revision ID: b8e1d4f7c2a3
Revises: e4b2c8f1a9d0
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8e1d4f7c2a3"
down_revision: Union[str, None] = "e4b2c8f1a9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Set when this revision creates the table (so downgrade can drop it safely).
_STRIKE20_CREATED_DEFERRED_TABLE = False


def upgrade() -> None:
    global _STRIKE20_CREATED_DEFERRED_TABLE
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())

    if "deferred_api_writes" not in names:
        _STRIKE20_CREATED_DEFERRED_TABLE = True
        op.create_table(
            "deferred_api_writes",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("service", sa.String(length=128), nullable=False),
            sa.Column("method", sa.String(length=512), nullable=False),
            sa.Column(
                "payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=64), nullable=False, server_default="pending"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_deferred_api_writes_service", "deferred_api_writes", ["service"])
        op.create_index("ix_deferred_api_writes_status", "deferred_api_writes", ["status"])
        op.create_index("ix_deferred_api_writes_created_at", "deferred_api_writes", ["created_at"])
        op.create_index(
            "ix_deferred_api_writes_svc_status_created",
            "deferred_api_writes",
            ["service", "status", "created_at"],
            unique=False,
        )
        return

    cols = {c["name"]: c for c in insp.get_columns("deferred_api_writes")}
    if "retry_count" not in cols:
        op.add_column(
            "deferred_api_writes",
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "last_error" not in cols:
        op.add_column("deferred_api_writes", sa.Column("last_error", sa.Text(), nullable=True))
    if "reconciled_at" not in cols:
        op.add_column(
            "deferred_api_writes",
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        )

    ct = cols.get("payload", {}).get("type")
    if ct is not None and str(ct).upper() in {"TEXT", "VARCHAR", "CHARACTER VARYING"}:
        op.execute(
            sa.text(
                "ALTER TABLE deferred_api_writes "
                "ALTER COLUMN payload TYPE jsonb USING payload::jsonb"
            )
        )

    existing_idx = {i["name"] for i in insp.get_indexes("deferred_api_writes")}
    if "ix_deferred_api_writes_svc_status_created" not in existing_idx:
        op.create_index(
            "ix_deferred_api_writes_svc_status_created",
            "deferred_api_writes",
            ["service", "status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    global _STRIKE20_CREATED_DEFERRED_TABLE
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "deferred_api_writes" not in insp.get_table_names():
        return
    if _STRIKE20_CREATED_DEFERRED_TABLE:
        op.drop_index("ix_deferred_api_writes_svc_status_created", table_name="deferred_api_writes")
        op.drop_index("ix_deferred_api_writes_created_at", table_name="deferred_api_writes")
        op.drop_index("ix_deferred_api_writes_status", table_name="deferred_api_writes")
        op.drop_index("ix_deferred_api_writes_service", table_name="deferred_api_writes")
        op.drop_table("deferred_api_writes")
        return
    idx = {i["name"] for i in insp.get_indexes("deferred_api_writes")}
    if "ix_deferred_api_writes_svc_status_created" in idx:
        op.drop_index("ix_deferred_api_writes_svc_status_created", table_name="deferred_api_writes")
    cols = {c["name"] for c in insp.get_columns("deferred_api_writes")}
    if "reconciled_at" in cols:
        op.drop_column("deferred_api_writes", "reconciled_at")
    if "last_error" in cols:
        op.drop_column("deferred_api_writes", "last_error")
    if "retry_count" in cols:
        op.drop_column("deferred_api_writes", "retry_count")
