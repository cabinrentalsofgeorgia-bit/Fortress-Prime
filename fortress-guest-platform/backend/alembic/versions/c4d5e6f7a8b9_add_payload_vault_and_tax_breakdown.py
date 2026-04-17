"""Add StreamlinePayloadVault table and tax_breakdown column on reservations.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-03
"""

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade() -> None:
    op.create_table(
        "streamline_payload_vault",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", sa.String(100), nullable=True, index=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("raw_payload", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.add_column(
        "reservations",
        sa.Column("tax_breakdown", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "tax_breakdown")
    op.drop_table("streamline_payload_vault")
