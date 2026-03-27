"""reconcile auxiliary runtime tables

Revision ID: c2b7d9e4a1f0
Revises: 8e2f8d1b6c4a
Create Date: 2026-03-22 01:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c2b7d9e4a1f0"
down_revision: Union[str, None] = "8e2f8d1b6c4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())

    if "knowledge_base_entries" not in tables:
        op.create_table(
            "knowledge_base_entries",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("question", sa.Text(), nullable=True),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("usage_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
            sa.Column("helpful_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
            sa.Column("not_helpful_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
            sa.Column("last_used_at", sa.TIMESTAMP(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("source", sa.String(length=100), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["property_id"],
                ["properties.id"],
                name="knowledge_base_entries_property_id_fkey",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "work_orders" not in tables:
        constraints: list[sa.Constraint] = [
            sa.ForeignKeyConstraint(
                ["property_id"],
                ["properties.id"],
                name="work_orders_property_id_fkey",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["reservation_id"],
                ["reservations.id"],
                name="work_orders_reservation_id_fkey",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["guest_id"],
                ["guests.id"],
                name="work_orders_guest_id_fkey",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ticket_number", name="work_orders_ticket_number_key"),
        ]
        if "messages" in tables:
            constraints.append(
                sa.ForeignKeyConstraint(
                    ["reported_via_message_id"],
                    ["messages.id"],
                    name="work_orders_reported_via_message_id_fkey",
                    ondelete="SET NULL",
                )
            )

        op.create_table(
            "work_orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("ticket_number", sa.String(length=50), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("reported_via_message_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column(
                "priority",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'medium'"),
            ),
            sa.Column(
                "status",
                sa.String(length=50),
                nullable=False,
                server_default=sa.text("'open'"),
            ),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("assigned_at", sa.TIMESTAMP(), nullable=True),
            sa.Column("resolved_at", sa.TIMESTAMP(), nullable=True),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
            sa.Column("cost_amount", sa.DECIMAL(10, 2), nullable=True),
            sa.Column("photo_urls", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            *constraints,
        )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_base_entries_category "
            "ON knowledge_base_entries (category)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_base_entries_property_id "
            "ON knowledge_base_entries (property_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_base_entries_is_active "
            "ON knowledge_base_entries (is_active)"
        )
    )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_property_id "
            "ON work_orders (property_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_reservation_id "
            "ON work_orders (reservation_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_guest_id "
            "ON work_orders (guest_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_priority "
            "ON work_orders (priority)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_status "
            "ON work_orders (status)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_work_orders_created_at "
            "ON work_orders (created_at)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS work_orders CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS knowledge_base_entries CASCADE"))
