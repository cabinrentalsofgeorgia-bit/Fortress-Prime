"""vault_documents schema integrity (Option A — union vocabulary).

Revision ID: d8e3c1f5b9a6
Revises: c4d8b1a3f7e2
Create Date: 2026-04-25

Pre-flight schema hardening before bulk vault ingestion (PR D).

Adds (idempotently):
  - FK on (case_slug) → legal.cases(case_slug) ON DELETE CASCADE
  - UNIQUE (case_slug, file_hash) — same hash allowed across cases,
    forbidden within a case (true dedup signal). Where a legacy
    `uq_vault_documents_case_slug_file_hash` UNIQUE INDEX already
    exists, it is converted into the named constraint
    `uq_vault_documents_case_hash` (no double index).
  - CHECK on processing_status with **union vocabulary** —
    accepts both spec target values (processing/complete/error)
    and the live-code writer values (vectorizing/completed/failed)
    plus 'locked_privileged' for the privilege-filter outcome and
    'ocr_failed' for PR D's image-only classification. Vocabulary
    cleanup is tracked as Issue #193.
  - Indexes for query patterns: case_slug, partial(active states),
    created_at DESC, file_hash.

Also creates legal.vault_documents itself when missing — fortress_db
ships without it; fortress_prod ships with it.

Schema columns (replicating fortress_prod exactly so fortress_db does
not diverge):
    id UUID PK, case_slug TEXT NOT NULL, file_name TEXT NOT NULL,
    nfs_path TEXT NOT NULL, mime_type TEXT NOT NULL,
    file_hash TEXT NOT NULL, file_size_bytes BIGINT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NULL, error_detail TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW().
"""
from __future__ import annotations

from alembic import op


revision = "d8e3c1f5b9a6"
down_revision = "c4d8b1a3f7e2"
branch_labels = None
depends_on = None


_STATUS_COMMENT = (
    "State machine. Active states: pending -> "
    "(processing|vectorizing) -> "
    "(complete|completed | ocr_failed | error|failed | locked_privileged). "
    "Vocabulary is currently bilingual (spec uses processing/complete/error; "
    "current code uses vectorizing/completed/failed). Bilingual vocabulary "
    "is intentional - both are accepted while the cleanup PR is pending. "
    "See Issue #193."
)


def upgrade() -> None:
    # 1. Table — replicates fortress_prod's columns exactly. fortress_db
    # currently lacks this table; fortress_prod has it (this CREATE is a
    # no-op there).
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.vault_documents (
            id                UUID NOT NULL,
            case_slug         TEXT NOT NULL,
            file_name         TEXT NOT NULL,
            nfs_path          TEXT NOT NULL,
            mime_type         TEXT NOT NULL,
            file_hash         TEXT NOT NULL,
            file_size_bytes   BIGINT NOT NULL,
            processing_status TEXT NOT NULL DEFAULT 'pending',
            chunk_count       INTEGER,
            error_detail      TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT vault_documents_pkey PRIMARY KEY (id)
        )
    """)

    # 2. FK to legal.cases.case_slug (case_slug is UNIQUE everywhere as
    # cases_case_slug_key — verified pre-flight).
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_vault_documents_case_slug'
                  AND conrelid = 'legal.vault_documents'::regclass
            ) THEN
                ALTER TABLE legal.vault_documents
                ADD CONSTRAINT fk_vault_documents_case_slug
                FOREIGN KEY (case_slug)
                REFERENCES legal.cases (case_slug)
                ON DELETE CASCADE;
            END IF;
        END $$;
    """)

    # 3. UNIQUE (case_slug, file_hash). fortress_prod already has a UNIQUE
    # INDEX named `uq_vault_documents_case_slug_file_hash`; convert it into
    # the named constraint without dropping (no rebuild). fortress_db has
    # no such index; create a fresh constraint.
    op.execute("""
        DO $$
        DECLARE
            has_named_constraint BOOLEAN;
            has_legacy_index     BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_vault_documents_case_hash'
                  AND conrelid = 'legal.vault_documents'::regclass
            ) INTO has_named_constraint;

            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'legal'
                  AND tablename  = 'vault_documents'
                  AND indexname  = 'uq_vault_documents_case_slug_file_hash'
            ) INTO has_legacy_index;

            IF has_named_constraint THEN
                NULL;       -- already done
            ELSIF has_legacy_index THEN
                ALTER TABLE legal.vault_documents
                ADD CONSTRAINT uq_vault_documents_case_hash
                UNIQUE USING INDEX uq_vault_documents_case_slug_file_hash;
            ELSE
                ALTER TABLE legal.vault_documents
                ADD CONSTRAINT uq_vault_documents_case_hash
                UNIQUE (case_slug, file_hash);
            END IF;
        END $$;
    """)

    # 4. CHECK on processing_status — union vocabulary.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_vault_documents_status'
                  AND conrelid = 'legal.vault_documents'::regclass
            ) THEN
                ALTER TABLE legal.vault_documents
                ADD CONSTRAINT chk_vault_documents_status
                CHECK (processing_status IN (
                    'pending',
                    'processing',
                    'vectorizing',
                    'complete',
                    'completed',
                    'ocr_failed',
                    'error',
                    'failed',
                    'locked_privileged'
                ));
            END IF;
        END $$;
    """)

    # 5. Indexes for query patterns.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_documents_case_slug "
        "ON legal.vault_documents (case_slug)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_documents_status "
        "ON legal.vault_documents (processing_status) "
        "WHERE processing_status IN ("
        "  'pending', 'processing', 'vectorizing', "
        "  'error', 'failed', 'ocr_failed'"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_documents_created_at "
        "ON legal.vault_documents (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_documents_file_hash "
        "ON legal.vault_documents (file_hash)"
    )

    op.execute(
        f"COMMENT ON COLUMN legal.vault_documents.processing_status IS "
        f"$${_STATUS_COMMENT}$$"
    )


def downgrade() -> None:
    # Drop only what this migration added. Do not drop the table itself
    # (fortress_prod has it independently) or the legacy unique index
    # (which we converted, not created).
    op.execute(
        "DROP INDEX IF EXISTS legal.idx_vault_documents_file_hash"
    )
    op.execute(
        "DROP INDEX IF EXISTS legal.idx_vault_documents_created_at"
    )
    op.execute(
        "DROP INDEX IF EXISTS legal.idx_vault_documents_status"
    )
    # idx_vault_documents_case_slug pre-existed in fortress_prod; do not drop.
    op.execute("""
        ALTER TABLE legal.vault_documents
        DROP CONSTRAINT IF EXISTS chk_vault_documents_status
    """)
    # Don't drop uq_vault_documents_case_hash — it carries the underlying
    # index which other queries depend on. A future hygiene pass can
    # rename back if needed.
    op.execute("""
        ALTER TABLE legal.vault_documents
        DROP CONSTRAINT IF EXISTS fk_vault_documents_case_slug
    """)
