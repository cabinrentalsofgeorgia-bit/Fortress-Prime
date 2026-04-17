"""create pending_sync table for offline booking buffer

Revision ID: c8f2d1a4b7e3
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "c8f2d1a4b7e3"
down_revision = None
branch_labels = ("offline_buffer",)
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "pending_sync" in inspector.get_table_names():
        return

    op.create_table(
        "pending_sync",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("property_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sync_type", sa.String(50), nullable=False, server_default="create_reservation"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pending_sync")
