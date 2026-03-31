"""Add Channex webhook events ledger.

Revision ID: f4c2b7d9e1a0
Revises: e8b1c4d7f9a2
Create Date: 2026-03-30 14:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f4c2b7d9e1a0"
down_revision: Union[str, Sequence[str], None] = "e8b1c4d7f9a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channex_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booking_id", sa.String(length=255), nullable=True),
        sa.Column("property_ref", sa.String(length=255), nullable=True),
        sa.Column("ota_source", sa.String(length=100), nullable=True),
        sa.Column("booking_status", sa.String(length=50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reservation_action", sa.String(length=32), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_channex_webhook_events_event_id"),
    )
    op.create_index(
        "ix_channex_webhook_events_status_created",
        "channex_webhook_events",
        ["processing_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_channex_webhook_events_booking_id",
        "channex_webhook_events",
        ["booking_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channex_webhook_events_booking_id", table_name="channex_webhook_events")
    op.drop_index("ix_channex_webhook_events_status_created", table_name="channex_webhook_events")
    op.drop_table("channex_webhook_events")
