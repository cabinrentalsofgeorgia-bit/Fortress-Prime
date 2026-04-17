"""Iron Dome core: accounts, journal_entries, journal_line_items

Revision ID: f8e9d0c1b2a3
Revises: 2c58318d85aa
Create Date: 2026-04-04

These tables back the Treasury / Prime snapshot SQL and revenue_consumer.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f8e9d0c1b2a3"
down_revision = "2c58318d85aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_accounts_code"),
    )
    op.create_index("ix_accounts_code", "accounts", ["code"], unique=False)

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=255), nullable=False),
        sa.Column("is_void", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("posted_by", sa.String(length=100), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_entries_reference",
        "journal_entries",
        ["reference_type", "reference_id"],
        unique=False,
    )
    op.create_index("ix_journal_entries_property_id", "journal_entries", ["property_id"], unique=False)

    op.create_table(
        "journal_line_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("journal_entry_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_line_items_journal_entry_id",
        "journal_line_items",
        ["journal_entry_id"],
        unique=False,
    )

    conn = op.get_bind()
    seed = [
        ("1010", "Operating Cash"),
        ("2000", "Owner Trust / Liability"),
        ("2100", "Accounts Payable"),
        ("4000", "Rental Revenue"),
        ("4010", "Rental Revenue (Alt)"),
        ("4100", "PM Revenue"),
        ("2200", "Other Liability"),
    ]
    for code, name in seed:
        conn.execute(
            sa.text("INSERT INTO accounts (code, name) VALUES (:code, :name) ON CONFLICT (code) DO NOTHING"),
            {"code": code, "name": name},
        )


def downgrade() -> None:
    op.drop_index("ix_journal_line_items_journal_entry_id", table_name="journal_line_items")
    op.drop_table("journal_line_items")
    op.drop_index("ix_journal_entries_property_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_reference", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_accounts_code", table_name="accounts")
    op.drop_table("accounts")
