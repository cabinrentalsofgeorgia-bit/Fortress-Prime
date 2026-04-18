"""add_commission_rate_to_magic_tokens

Adds commission_rate NUMERIC(5,4) NULL to owner_magic_tokens so the rate
set by the admin at invite-creation time travels through to accept_invite().

NULL is allowed because the 68 existing test tokens were created before
this column existed; they are all test rows and will never trigger real
statement sends.

New tokens created after this migration MUST have commission_rate set.
accept_invite() will raise a clear error if it finds a NULL rate.

Revision ID: c1a8f3b7e2d4
Revises: e7c3f9a1b5d2
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1a8f3b7e2d4"
down_revision: Union[str, Sequence[str], None] = "e7c3f9a1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE owner_magic_tokens
            ADD COLUMN commission_rate NUMERIC(5,4) NULL
    """))
    op.execute(sa.text("""
        ALTER TABLE owner_magic_tokens
            ADD CONSTRAINT chk_omt_commission_rate
            CHECK (commission_rate >= 0 AND commission_rate <= 0.5000)
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE owner_magic_tokens
            DROP CONSTRAINT IF EXISTS chk_omt_commission_rate,
            DROP COLUMN IF EXISTS commission_rate
    """))
