"""create storefront_intent_events for consented intent signals

Revision ID: d8e1f3a9c2b4
Revises: b2c8e1f4a9d0
Create Date: 2026-03-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d8e1f3a9c2b4"
down_revision: Union[str, Sequence[str], None] = "b2c8e1f4a9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "storefront_intent_events" in inspector.get_table_names():
        return
    op.create_table(
        "storefront_intent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_fp", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("consent_marketing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("property_slug", sa.String(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storefront_intent_session_created", "storefront_intent_events", ["session_fp", "created_at"])
    op.create_index("ix_storefront_intent_created", "storefront_intent_events", ["created_at"])
    op.create_index(op.f("ix_storefront_intent_events_session_fp"), "storefront_intent_events", ["session_fp"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "storefront_intent_events" not in inspector.get_table_names():
        return
    op.drop_index(op.f("ix_storefront_intent_events_session_fp"), table_name="storefront_intent_events")
    op.drop_index("ix_storefront_intent_created", table_name="storefront_intent_events")
    op.drop_index("ix_storefront_intent_session_created", table_name="storefront_intent_events")
    op.drop_table("storefront_intent_events")
