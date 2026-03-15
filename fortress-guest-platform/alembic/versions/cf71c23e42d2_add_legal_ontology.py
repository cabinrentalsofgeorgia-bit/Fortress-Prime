"""add_legal_ontology

Revision ID: cf71c23e42d2
Revises: m7g8h9i0j1k2
Create Date: 2026-03-15 10:02:14.258367
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cf71c23e42d2"
down_revision: Union[str, Sequence[str], None] = "m7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index("ix_legal_entities_name", "entities", ["name"], unique=False, schema="legal")
    op.create_index("ix_legal_entities_type", "entities", ["type"], unique=False, schema="legal")

    op.create_table(
        "distillation_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("context_hash", sa.String(length=128), nullable=False),
        sa.Column("frontier_insight", sa.Text(), nullable=False),
        sa.Column("local_correction", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index(
        "ix_legal_distillation_memory_context_hash",
        "distillation_memory",
        ["context_hash"],
        unique=True,
        schema="legal",
    )

    op.create_table(
        "case_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_slug", sa.String(length=255), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("nas_path", sa.Text(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=255), nullable=True),
        sa.Column("sha256_hash", sa.String(length=128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["legal.entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index("ix_legal_case_evidence_case_slug", "case_evidence", ["case_slug"], unique=False, schema="legal")
    op.create_index("ix_legal_case_evidence_entity_id", "case_evidence", ["entity_id"], unique=False, schema="legal")
    op.create_index(
        "ix_legal_case_evidence_qdrant_point_id",
        "case_evidence",
        ["qdrant_point_id"],
        unique=False,
        schema="legal",
    )
    op.create_index("ix_legal_case_evidence_sha256_hash", "case_evidence", ["sha256_hash"], unique=False, schema="legal")

    op.create_table(
        "timeline_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_slug", sa.String(length=255), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_evidence_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["legal.case_evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="legal",
    )
    op.create_index("ix_legal_timeline_events_case_slug", "timeline_events", ["case_slug"], unique=False, schema="legal")
    op.create_index("ix_legal_timeline_events_event_date", "timeline_events", ["event_date"], unique=False, schema="legal")
    op.create_index(
        "ix_legal_timeline_events_source_evidence_id",
        "timeline_events",
        ["source_evidence_id"],
        unique=False,
        schema="legal",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_legal_timeline_events_source_evidence_id", table_name="timeline_events", schema="legal")
    op.drop_index("ix_legal_timeline_events_event_date", table_name="timeline_events", schema="legal")
    op.drop_index("ix_legal_timeline_events_case_slug", table_name="timeline_events", schema="legal")
    op.drop_table("timeline_events", schema="legal")

    op.drop_index("ix_legal_case_evidence_sha256_hash", table_name="case_evidence", schema="legal")
    op.drop_index("ix_legal_case_evidence_qdrant_point_id", table_name="case_evidence", schema="legal")
    op.drop_index("ix_legal_case_evidence_entity_id", table_name="case_evidence", schema="legal")
    op.drop_index("ix_legal_case_evidence_case_slug", table_name="case_evidence", schema="legal")
    op.drop_table("case_evidence", schema="legal")

    op.drop_index("ix_legal_distillation_memory_context_hash", table_name="distillation_memory", schema="legal")
    op.drop_table("distillation_memory", schema="legal")

    op.drop_index("ix_legal_entities_type", table_name="entities", schema="legal")
    op.drop_index("ix_legal_entities_name", table_name="entities", schema="legal")
    op.drop_table("entities", schema="legal")

