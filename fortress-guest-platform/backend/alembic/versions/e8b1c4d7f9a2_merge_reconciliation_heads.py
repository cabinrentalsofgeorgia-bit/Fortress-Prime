"""merge reconciliation heads

Revision ID: e8b1c4d7f9a2
Revises: 9b3e8218df41, c7d8e9f0a1b2, d1f4e8c2b7a9
Create Date: 2026-03-29 18:40:00.000000
"""

from typing import Sequence, Union


revision: str = "e8b1c4d7f9a2"
down_revision: Union[str, Sequence[str], None] = (
    "9b3e8218df41",
    "c7d8e9f0a1b2",
    "d1f4e8c2b7a9",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads without schema changes."""
    pass


def downgrade() -> None:
    """Split merged heads without schema changes."""
    pass
