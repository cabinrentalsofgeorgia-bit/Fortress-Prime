"""Strict Whitelist: ensure is_optional column and force-update Check-In/Check-Out fees.

Revision ID: d5e6f7a8b9c0
Revises: b3c4d5e6f7a8
Create Date: 2026-04-03

Ensures:
  1. fees.is_optional Boolean column exists (idempotent).
  2. Any fee containing 'Check-In' or 'Check-Out' (case-insensitive) is marked optional.
  3. These fees are mapped to TaxBucket.EXEMPT via backend classification rules
     (non-taxable pass-through per legacy audit).
"""

revision = "d5e6f7a8b9c0"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("fees")}

    if "is_optional" not in columns:
        op.add_column(
            "fees",
            sa.Column(
                "is_optional",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    op.execute(
        "UPDATE fees SET is_optional = true, updated_at = now() "
        "WHERE LOWER(name) LIKE '%check-in%' "
        "   OR LOWER(name) LIKE '%check-out%' "
        "   OR LOWER(name) LIKE '%check in%' "
        "   OR LOWER(name) LIKE '%check out%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE fees SET is_optional = false, updated_at = now() "
        "WHERE LOWER(name) LIKE '%check-in%' "
        "   OR LOWER(name) LIKE '%check-out%' "
        "   OR LOWER(name) LIKE '%check in%' "
        "   OR LOWER(name) LIKE '%check out%'"
    )
