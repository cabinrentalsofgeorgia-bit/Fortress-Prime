"""add legal graph and discovery schema models

Revision ID: db04ffbd9fc8
Revises: a1814dabe32e
Create Date: 2026-03-13 17:22:22.218438
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "db04ffbd9fc8"
down_revision: Union[str, Sequence[str], None] = "a1814dabe32e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS legal")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'legal' AND table_name = 'case_graph_nodes'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'legal' AND table_name = 'case_graph_nodes' AND column_name = 'case_id'
            ) THEN
                ALTER TABLE legal.case_graph_nodes RENAME TO case_graph_nodes_legacy_v1;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'legal' AND table_name = 'case_graph_edges'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'legal' AND table_name = 'case_graph_edges' AND column_name = 'case_id'
            ) THEN
                ALTER TABLE legal.case_graph_edges RENAME TO case_graph_edges_legacy_v1;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'legal' AND table_name = 'discovery_draft_packs'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'legal' AND table_name = 'discovery_draft_packs' AND column_name = 'case_id'
            ) THEN
                ALTER TABLE legal.discovery_draft_packs RENAME TO discovery_draft_packs_legacy_v1;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'legal' AND table_name = 'discovery_draft_items'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'legal' AND table_name = 'discovery_draft_items' AND column_name = 'item_number'
            ) THEN
                ALTER TABLE legal.discovery_draft_items RENAME TO discovery_draft_items_legacy_v1;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.legal_cases (
            id UUID PRIMARY KEY,
            slug VARCHAR(255) NOT NULL UNIQUE,
            court VARCHAR(255) NOT NULL,
            jurisdiction VARCHAR(255) NOT NULL,
            status VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_legal_legal_cases_slug ON legal.legal_cases (slug)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.case_graph_nodes (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES legal.legal_cases(id) ON DELETE CASCADE,
            entity_type VARCHAR(64) NOT NULL,
            label VARCHAR(500) NOT NULL,
            metadata JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_case_graph_nodes_case_id ON legal.case_graph_nodes (case_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.case_graph_edges (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES legal.legal_cases(id) ON DELETE CASCADE,
            source_node_id UUID NOT NULL REFERENCES legal.case_graph_nodes(id) ON DELETE CASCADE,
            target_node_id UUID NOT NULL REFERENCES legal.case_graph_nodes(id) ON DELETE CASCADE,
            relationship_type VARCHAR(128) NOT NULL,
            weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            source_ref VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_case_graph_edges_case_id ON legal.case_graph_edges (case_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_case_graph_edges_source_node_id ON legal.case_graph_edges (source_node_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_case_graph_edges_target_node_id ON legal.case_graph_edges (target_node_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.discovery_draft_packs (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES legal.legal_cases(id) ON DELETE CASCADE,
            pack_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_discovery_draft_packs_case_id ON legal.discovery_draft_packs (case_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.discovery_draft_items (
            id UUID PRIMARY KEY,
            pack_id UUID NOT NULL REFERENCES legal.discovery_draft_packs(id) ON DELETE CASCADE,
            item_number INTEGER NOT NULL,
            content TEXT NOT NULL,
            relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            proportionality_flag BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_discovery_draft_items_pack_id ON legal.discovery_draft_items (pack_id)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_discovery_draft_items_pack_id")
    op.execute("DROP TABLE IF EXISTS legal.discovery_draft_items")

    op.execute("DROP INDEX IF EXISTS legal.ix_legal_discovery_draft_packs_case_id")
    op.execute("DROP TABLE IF EXISTS legal.discovery_draft_packs")

    op.execute("DROP INDEX IF EXISTS legal.ix_legal_case_graph_edges_target_node_id")
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_case_graph_edges_source_node_id")
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_case_graph_edges_case_id")
    op.execute("DROP TABLE IF EXISTS legal.case_graph_edges")

    op.execute("DROP INDEX IF EXISTS legal.ix_legal_case_graph_nodes_case_id")
    op.execute("DROP TABLE IF EXISTS legal.case_graph_nodes")

    op.execute("DROP INDEX IF EXISTS legal.ix_legal_legal_cases_slug")
    op.execute("DROP TABLE IF EXISTS legal.legal_cases")
