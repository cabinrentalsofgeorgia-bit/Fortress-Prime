"""vault_documents.processing_status — allow 'qdrant_upsert_failed' (Phase A.1 for Issue #228).

Revision ID: o0a1b2c3d4e5
Revises: n9a1b2c3d4e5
Create Date: 2026-04-26

Phase A.1 of the Issue #228 fix.

Extends the `chk_vault_documents_status` CHECK constraint to allow the new
`qdrant_upsert_failed` value that Phase B's `process_vault_upload` writer
will produce when a Qdrant batch upsert fails (instead of silently
recording `processing_status='completed'` with zero indexed points,
which is the #228 pathology).

The constraint is dropped + re-added with the extended vocabulary —
PostgreSQL doesn't support modifying a CHECK constraint in place, and
ADD CONSTRAINT IF NOT EXISTS doesn't exist for CHECK constraints, so the
DROP/ADD pair guarded by IF EXISTS is the idempotent pattern.

Vocabulary after this migration (additive only — no value removed):
  pending, processing, vectorizing,
  complete, completed, ocr_failed,
  error, failed, locked_privileged,
  qdrant_upsert_failed                                    (NEW — Phase A.1)

Vocabulary cleanup (the bilingual processing/vectorizing,
complete/completed, error/failed pairs) remains tracked under Issue #194
and is out of scope for the #228 fix sprint.

Application targets: fortress_prod, fortress_db, fortress_shadow_test.
Skip: fortress_shadow (per Issue #204).
"""
from __future__ import annotations

from alembic import op


revision = "o0a1b2c3d4e5"
down_revision = "n9a1b2c3d4e5"
branch_labels = None
depends_on = None


_STATUSES_NEW = (
    "'pending', 'processing', 'vectorizing', "
    "'complete', 'completed', 'ocr_failed', "
    "'error', 'failed', 'locked_privileged', "
    "'qdrant_upsert_failed'"
)

_STATUSES_OLD = (
    "'pending', 'processing', 'vectorizing', "
    "'complete', 'completed', 'ocr_failed', "
    "'error', 'failed', 'locked_privileged'"
)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE legal.vault_documents
        DROP CONSTRAINT IF EXISTS chk_vault_documents_status
    """)
    op.execute(f"""
        ALTER TABLE legal.vault_documents
        ADD CONSTRAINT chk_vault_documents_status
        CHECK (processing_status IN ({_STATUSES_NEW}))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE legal.vault_documents
        DROP CONSTRAINT IF EXISTS chk_vault_documents_status
    """)
    op.execute(f"""
        ALTER TABLE legal.vault_documents
        ADD CONSTRAINT chk_vault_documents_status
        CHECK (processing_status IN ({_STATUSES_OLD}))
    """)
