"""Add delivery_channel to agent_queue.

Revision ID: 9b3e8218df41
Revises: c4a6c2e5d1b7
Create Date: 2026-03-29 16:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b3e8218df41"
down_revision: Union[str, Sequence[str], None] = "c4a6c2e5d1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_queue",
        sa.Column("delivery_channel", sa.String(length=20), nullable=False, server_default="email"),
    )


def downgrade() -> None:
    op.drop_column("agent_queue", "delivery_channel")
