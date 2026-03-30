"""create intelligence ledger

Revision ID: c3f9a7d6e2b1
Revises: a13f4c7d9b21
Create Date: 2026-03-24 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3f9a7d6e2b1"
down_revision: Union[str, Sequence[str], None] = "a13f4c7d9b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "intelligence_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("market", sa.String(length=128), nullable=False),
        sa.Column("locality", sa.String(length=128), nullable=True),
        sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("query_topic", sa.String(length=120), nullable=True),
        sa.Column("scout_query", sa.Text(), nullable=True),
        sa.Column("scout_run_key", sa.String(length=120), nullable=True),
        sa.Column("source_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("grounding_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("finding_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_hash", name="uq_intelligence_ledger_dedupe_hash"),
    )
    op.create_index(op.f("ix_intelligence_ledger_category"), "intelligence_ledger", ["category"], unique=False)
    op.create_index(
        "ix_intelligence_ledger_category_discovered",
        "intelligence_ledger",
        ["category", "discovered_at"],
        unique=False,
    )
    op.create_index(op.f("ix_intelligence_ledger_dedupe_hash"), "intelligence_ledger", ["dedupe_hash"], unique=False)
    op.create_index(op.f("ix_intelligence_ledger_discovered_at"), "intelligence_ledger", ["discovered_at"], unique=False)
    op.create_index(op.f("ix_intelligence_ledger_locality"), "intelligence_ledger", ["locality"], unique=False)
    op.create_index(op.f("ix_intelligence_ledger_market"), "intelligence_ledger", ["market"], unique=False)
    op.create_index(
        "ix_intelligence_ledger_market_discovered",
        "intelligence_ledger",
        ["market", "discovered_at"],
        unique=False,
    )
    op.create_index(op.f("ix_intelligence_ledger_query_topic"), "intelligence_ledger", ["query_topic"], unique=False)
    op.create_index(op.f("ix_intelligence_ledger_scout_run_key"), "intelligence_ledger", ["scout_run_key"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_intelligence_ledger_scout_run_key"), table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_query_topic"), table_name="intelligence_ledger")
    op.drop_index("ix_intelligence_ledger_market_discovered", table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_market"), table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_locality"), table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_discovered_at"), table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_dedupe_hash"), table_name="intelligence_ledger")
    op.drop_index("ix_intelligence_ledger_category_discovered", table_name="intelligence_ledger")
    op.drop_index(op.f("ix_intelligence_ledger_category"), table_name="intelligence_ledger")
    op.drop_table("intelligence_ledger")
