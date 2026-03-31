"""Legacy Alembic branch anchor recovered from live database history.

Revision ID: a9c1e4f8b2d0
Revises: None
Create Date: 2026-03-27

This is a compatibility anchor for a historical migration branch that is still
referenced by live environments through revision `c7d8e9f0a1b2`.

The original parent revision is not present in the current repository checkout.
We intentionally model it as a no-op root so Alembic can represent the branch
lineage during inspection and recovery planning.

Important:
- This file does NOT imply that a full `alembic upgrade heads` is currently safe
  on environments stamped to the legacy branch.
- See `docs/permission-matrix.md` and operational notes in the chat history for
  the migration-repair context.
"""

from typing import Sequence, Union


revision: str = "a9c1e4f8b2d0"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Compatibility anchor only."""
    pass


def downgrade() -> None:
    """Compatibility anchor only."""
    pass
