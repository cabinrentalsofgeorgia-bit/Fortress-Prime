"""Harden sovereign ledger: immutability triggers, hash-chain columns, uniqueness.

Revision ID: g9a8b7c6d5e4
Revises: f7a8b9c0d1e2
Create Date: 2026-04-03
"""

from __future__ import annotations

revision = "g9a8b7c6d5e4"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION prevent_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Immutable table: UPDATE and DELETE are strictly forbidden on %', TG_TABLE_NAME;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""
    )

    op.execute(
        """
CREATE TRIGGER trg_immutable_trust_ledger_entries
    BEFORE UPDATE OR DELETE ON trust_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
"""
    )
    op.execute(
        """
CREATE TRIGGER trg_immutable_trust_transactions
    BEFORE UPDATE OR DELETE ON trust_transactions
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
"""
    )
    op.execute(
        """
CREATE TRIGGER trg_immutable_streamline_payload_vault
    BEFORE UPDATE OR DELETE ON streamline_payload_vault
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
"""
    )

    op.add_column(
        "trust_transactions",
        sa.Column("signature", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "trust_transactions",
        sa.Column("previous_signature", sa.String(length=64), nullable=True),
    )

    op.drop_index(
        op.f("ix_trust_transactions_streamline_event_id"),
        table_name="trust_transactions",
    )

    op.create_unique_constraint(
        "uq_trust_transactions_signature",
        "trust_transactions",
        ["signature"],
    )
    op.create_index(
        "ix_trust_transactions_previous_signature",
        "trust_transactions",
        ["previous_signature"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_trust_transactions_streamline_event_id",
        "trust_transactions",
        ["streamline_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_trust_transactions_streamline_event_id",
        "trust_transactions",
        type_="unique",
    )
    op.drop_index(
        "ix_trust_transactions_previous_signature",
        table_name="trust_transactions",
    )
    op.drop_constraint(
        "uq_trust_transactions_signature",
        "trust_transactions",
        type_="unique",
    )

    op.create_index(
        op.f("ix_trust_transactions_streamline_event_id"),
        "trust_transactions",
        ["streamline_event_id"],
        unique=False,
    )

    op.drop_column("trust_transactions", "previous_signature")
    op.drop_column("trust_transactions", "signature")

    op.execute("DROP TRIGGER IF EXISTS trg_immutable_trust_ledger_entries ON trust_ledger_entries;")
    op.execute("DROP TRIGGER IF EXISTS trg_immutable_trust_transactions ON trust_transactions;")
    op.execute("DROP TRIGGER IF EXISTS trg_immutable_streamline_payload_vault ON streamline_payload_vault;")
    op.execute("DROP FUNCTION IF EXISTS prevent_mutation();")
