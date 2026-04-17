"""create parity_audits table for ledger/Streamline reconciliation

Revision ID: a2b3c4d5e6f7
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "a2b3c4d5e6f7"
down_revision = None
branch_labels = ("parity_audit",)
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "parity_audits" in inspector.get_table_names():
        return

    op.create_table(
        "parity_audits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("confirmation_id", sa.String(100), nullable=False, index=True),
        sa.Column("local_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("streamline_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("delta", sa.Numeric(12, 2), nullable=False),
        sa.Column("local_breakdown", JSONB, nullable=False, server_default="{}"),
        sa.Column("streamline_breakdown", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("parity_audits")
