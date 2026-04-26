"""vault_documents.vector_ids — Qdrant point-id accumulator for #228 silent-failure detection.

Revision ID: n9a1b2c3d4e5
Revises: d4e5f6a7b8c9
Create Date: 2026-04-26

Phase A of the Issue #228 fix (silent Qdrant upsert failures during legal vault
ingestion).

Adds (idempotently):

  - `vector_ids UUID[]` — accumulator of Qdrant point UUIDs returned by
    successful upsert batches inside `process_vault_upload`. NULL means
    "the upload code did not record any successful upsert points for this
    row." When `chunk_count > 0` (vault row claims it produced N chunks)
    AND `vector_ids IS NULL` (zero chunks confirmed indexed), that gap is
    a Issue #228 silent failure.

  - `idx_vault_documents_vector_ids_partial` — partial btree index on
    `(id) WHERE vector_ids IS NULL AND chunk_count > 0`. Targets the sweep
    query that finds silent failures. Stays small because the partial
    predicate excludes the steady-state majority (rows that succeeded
    fully or have no chunks).

The CHECK constraint on `processing_status` does NOT add the new
`qdrant_upsert_failed` value yet — that is part of Phase B (which writes
the new status from `process_vault_upload`'s batch-failure branch).
Adding the constraint update before the writer code lands would make this
column purely additive; adding it now without writers is harmless but
out of Phase A scope per the operator's spec.

Application notes:
  - Apply target DBs: fortress_prod, fortress_db, fortress_shadow_test.
  - Skip: fortress_shadow (per Issue #204 — alembic_version orphan; the
    operator's spec excludes it).
  - The alembic chain has many unreferenced heads (Issue #204 territory).
    This migration's `down_revision` points at fortress_prod's actual
    head (`d4e5f6a7b8c9`); fortress_db's head (`7a1b2c3d4e5f`) is
    independently the orphan #204 tracks. Direct psql application is
    used in Phase A so per-DB confirmation is explicit; the file is
    checked in for the alembic chain.
"""
from __future__ import annotations

from alembic import op


revision = "n9a1b2c3d4e5"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE legal.vault_documents
        ADD COLUMN IF NOT EXISTS vector_ids UUID[] DEFAULT NULL
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vault_documents_vector_ids_partial
        ON legal.vault_documents (id)
        WHERE vector_ids IS NULL AND chunk_count > 0
    """)

    op.execute(
        "COMMENT ON COLUMN legal.vault_documents.vector_ids IS "
        "$$Accumulator of Qdrant point UUIDs from successful upsert batches "
        "in process_vault_upload. NULL + chunk_count>0 indicates an Issue #228 "
        "silent failure — vault row claims chunks were produced but no Qdrant "
        "points were recorded as indexed. Populated by Phase B writer; "
        "backfilled for pre-fix rows by Phase C script.$$"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS legal.idx_vault_documents_vector_ids_partial"
    )
    op.execute("""
        ALTER TABLE legal.vault_documents
        DROP COLUMN IF EXISTS vector_ids
    """)
