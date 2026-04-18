"""Add fee_type and percentage_rate columns to fees table.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-03
"""

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = ("bc39f7e1a442",)  # fees table must exist before adding columns

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "fees",
        sa.Column(
            "fee_type",
            sa.String(20),
            nullable=False,
            server_default="flat",
        ),
    )
    op.add_column(
        "fees",
        sa.Column(
            "percentage_rate",
            sa.Numeric(6, 3),
            nullable=True,
        ),
    )

    op.execute(
        "UPDATE fees SET fee_type = 'percentage', percentage_rate = 3.000, flat_amount = 0 "
        "WHERE name = 'Processing Fee'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE fees SET flat_amount = 81.00 "
        "WHERE name = 'Processing Fee' AND fee_type = 'percentage'"
    )
    op.drop_column("fees", "percentage_rate")
    op.drop_column("fees", "fee_type")
