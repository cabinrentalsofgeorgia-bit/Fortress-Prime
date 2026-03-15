"""add legal deposition target and funnel models

Revision ID: c8d7e6f5a4b3
Revises: db04ffbd9fc8
Create Date: 2026-03-13 20:05:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d7e6f5a4b3"
down_revision: Union[str, Sequence[str], None] = "db04ffbd9fc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS legal")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = 'deposition_target_status'
                  AND n.nspname = 'legal'
            ) THEN
                CREATE TYPE legal.deposition_target_status AS ENUM ('drafting', 'ready', 'completed');
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.deposition_targets (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES legal.legal_cases(id) ON DELETE CASCADE,
            entity_name VARCHAR(255) NOT NULL,
            role VARCHAR(128) NOT NULL,
            status legal.deposition_target_status NOT NULL DEFAULT 'drafting',
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_deposition_targets_case_id ON legal.deposition_targets (case_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_deposition_targets_entity_name ON legal.deposition_targets (entity_name)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal.cross_exam_funnels (
            id UUID PRIMARY KEY,
            target_id UUID NOT NULL REFERENCES legal.deposition_targets(id) ON DELETE CASCADE,
            contradiction_edge_id UUID NOT NULL REFERENCES legal.case_graph_edges(id) ON DELETE CASCADE,
            topic VARCHAR(500) NOT NULL,
            lock_in_questions JSONB NOT NULL,
            the_strike_document VARCHAR(1000) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_cross_exam_funnels_target_id ON legal.cross_exam_funnels (target_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_cross_exam_funnels_contradiction_edge_id "
        "ON legal.cross_exam_funnels (contradiction_edge_id)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_cross_exam_funnels_contradiction_edge_id")
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_cross_exam_funnels_target_id")
    op.execute("DROP TABLE IF EXISTS legal.cross_exam_funnels")

    op.execute("DROP INDEX IF EXISTS legal.ix_legal_deposition_targets_entity_name")
    op.execute("DROP INDEX IF EXISTS legal.ix_legal_deposition_targets_case_id")
    op.execute("DROP TABLE IF EXISTS legal.deposition_targets")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = 'deposition_target_status'
                  AND n.nspname = 'legal'
            ) THEN
                DROP TYPE legal.deposition_target_status;
            END IF;
        END $$;
        """
    )
