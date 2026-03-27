"""concierge_recovery_dispatches for Enticer Swarm idempotency

Revision ID: f9b2c3d4e5a6
Revises: e7f1a2b3c4d5
Create Date: 2026-03-23 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f9b2c3d4e5a6"
down_revision: Union[str, Sequence[str], None] = "e7f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "concierge_recovery_dispatches" in inspector.get_table_names():
        return
    op.create_table(
        "concierge_recovery_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_fp", sa.String(length=64), nullable=True),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("template_key", sa.String(length=64), server_default="abandon_cart_v1", nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="sent", nullable=False),
        sa.Column(
            "provider_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crd_guest_channel_created", "concierge_recovery_dispatches", ["guest_id", "channel", "created_at"])
    op.create_index(op.f("ix_crd_session_fp"), "concierge_recovery_dispatches", ["session_fp"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "concierge_recovery_dispatches" not in inspector.get_table_names():
        return
    op.drop_index(op.f("ix_crd_session_fp"), table_name="concierge_recovery_dispatches")
    op.drop_index("ix_crd_guest_channel_created", table_name="concierge_recovery_dispatches")
    op.drop_table("concierge_recovery_dispatches")
