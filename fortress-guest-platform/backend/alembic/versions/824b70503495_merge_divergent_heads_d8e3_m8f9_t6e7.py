"""merge divergent heads d8e3 m8f9 t6e7

Revision ID: 824b70503495
Revises: d8e3c1f5b9a6, m8f9a1b2c3d4, t6e7f8g9h0a1
Create Date: 2026-05-01 20:50:10.433690

Closes Issue #279 — divergent fortress_db heads.

Issue #279 (filed 2026-04-29) named two heads: q2b3c4d5e6f7 and r3c4d5e6f7g8.
Both became chain ancestors after FLOS Phase 0a-7 (s4d5e6f7g8h9) and 0a-8
(t6e7f8g9h0a1) landed on top of r3c4d5e6f7g8. By the time of this merge
(2026-05-01) three file-tree heads existed:

  - d8e3c1f5b9a6  vault_documents schema integrity (PR D lineage)
  - m8f9a1b2c3d4  NIM/NeMo container catalog inventory
  - t6e7f8g9h0a1  FLOS Phase 0a-8 role grants on legal mail intake

This revision merges all three into a single canonical head. Empty
upgrade()/downgrade() — purely structural; no schema changes.

Issue #204 (orphan stamp 7a1b2c3d4e5f on fortress_db.alembic_version) is
NOT addressed here. That is a separate stamp-row problem, not a file-tree
divergence, and is tracked separately.

Unblocks: M3 activation step 4 (alembic upgrade head against
SPARK1_DATABASE_URL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '824b70503495'
down_revision: Union[str, Sequence[str], None] = ('d8e3c1f5b9a6', 'm8f9a1b2c3d4', 't6e7f8g9h0a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
