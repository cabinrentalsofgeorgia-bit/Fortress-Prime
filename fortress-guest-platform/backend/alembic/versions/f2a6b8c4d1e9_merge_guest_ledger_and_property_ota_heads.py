"""merge guest ledger and property ota heads

Revision ID: f2a6b8c4d1e9
Revises: 5e7c1a9d4b2f, c8f1a2d4e6b7
Create Date: 2026-03-26 21:40:00.000000

"""
from typing import Sequence, Union


revision: str = "f2a6b8c4d1e9"
down_revision: Union[str, Sequence[str], None] = ("5e7c1a9d4b2f", "c8f1a2d4e6b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads without schema changes."""
    pass


def downgrade() -> None:
    """Split merged heads without schema changes."""
    pass
