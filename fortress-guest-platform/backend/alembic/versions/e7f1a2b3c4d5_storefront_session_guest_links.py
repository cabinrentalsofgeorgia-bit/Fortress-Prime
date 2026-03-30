"""storefront_session_guest_links — bridge session_fp to guest after checkout hold

Revision ID: e7f1a2b3c4d5
Revises: d8e1f3a9c2b4
Create Date: 2026-03-23 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d8e1f3a9c2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "storefront_session_guest_links" in inspector.get_table_names():
        return
    op.create_table(
        "storefront_session_guest_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_fp", sa.String(length=64), nullable=False),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_hold_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="checkout_hold"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reservation_hold_id"], ["reservation_holds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssgl_session_fp_created", "storefront_session_guest_links", ["session_fp", "created_at"])
    op.create_index("ix_ssgl_guest_id", "storefront_session_guest_links", ["guest_id"])
    op.create_index(op.f("ix_ssgl_session_fp"), "storefront_session_guest_links", ["session_fp"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "storefront_session_guest_links" not in inspector.get_table_names():
        return
    op.drop_index(op.f("ix_ssgl_session_fp"), table_name="storefront_session_guest_links")
    op.drop_index("ix_ssgl_guest_id", table_name="storefront_session_guest_links")
    op.drop_index("ix_ssgl_session_fp_created", table_name="storefront_session_guest_links")
    op.drop_table("storefront_session_guest_links")
