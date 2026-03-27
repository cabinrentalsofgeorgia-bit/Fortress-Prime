"""add agent registry is_active flag

Revision ID: 91b1e1b4c3d2
Revises: 6c4cbfecea6c
Create Date: 2026-03-22 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "91b1e1b4c3d2"
down_revision: Union[str, Sequence[str], None] = "6c4cbfecea6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_registry",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(op.f("ix_agent_registry_is_active"), "agent_registry", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_registry_is_active"), table_name="agent_registry")
    op.drop_column("agent_registry", "is_active")
