"""Add legal.ingest_runs audit-trail table.

Revision ID: c4d8b1a3f7e2
Revises: e7f9a3c2d8b1
Create Date: 2026-04-25

Audit trail for case-scoped ingest operations (OCR sweeps, vault
ingestion, future ASR runs, re-ingest passes). One row per script
invocation. Status state machine:

    running → complete | error | interrupted

Foreign key to legal.cases.case_slug ON DELETE CASCADE — when a case
is deleted, its ingest history goes with it.

Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS. UNIQUE on
legal.cases.case_slug already exists (`cases_case_slug_key`) across
all three legal-bearing databases per pre-flight verification, so
this migration does not touch that constraint.
"""
from __future__ import annotations

from alembic import op


revision = "c4d8b1a3f7e2"
down_revision = "e7f9a3c2d8b1"
branch_labels = None
depends_on = None


_TABLE_COMMENT = (
    "Audit trail for case-scoped ingest operations (OCR, vault, ASR). "
    "One row per script invocation. "
    "Status state machine: running -> complete | error | interrupted."
)


def upgrade() -> None:
    # Sanity: ensure UNIQUE(case_slug) exists on legal.cases. Pre-flight
    # showed `cases_case_slug_key` already present in fortress_prod,
    # fortress_db, and fortress_shadow, but a fresh DB might not have it
    # yet — add only if missing.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'legal.cases'::regclass
                  AND contype  = 'u'
                  AND conkey = ARRAY[
                    (SELECT attnum FROM pg_attribute
                     WHERE attrelid = 'legal.cases'::regclass
                       AND attname = 'case_slug')::smallint
                  ]
            ) THEN
                ALTER TABLE legal.cases
                ADD CONSTRAINT uq_cases_case_slug UNIQUE (case_slug);
            END IF;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.ingest_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_slug       TEXT NOT NULL,
            script_name     TEXT NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at        TIMESTAMPTZ,
            args            JSONB NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running','complete','error','interrupted')),
            manifest_path   TEXT,
            total_files     INTEGER,
            processed       INTEGER,
            errored         INTEGER,
            skipped         INTEGER,
            error_summary   TEXT,
            host            TEXT,
            pid             INTEGER,
            runtime_seconds NUMERIC(12,3),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT fk_ingest_runs_case_slug
                FOREIGN KEY (case_slug) REFERENCES legal.cases (case_slug)
                ON DELETE CASCADE
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_runs_case_slug "
        "ON legal.ingest_runs (case_slug)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_runs_status "
        "ON legal.ingest_runs (status) WHERE status IN ('running','error')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_runs_started_at "
        "ON legal.ingest_runs (started_at DESC)"
    )

    op.execute(f"COMMENT ON TABLE legal.ingest_runs IS $${_TABLE_COMMENT}$$")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS legal.ingest_runs")
    # Do NOT drop uq_cases_case_slug — it predates this migration in
    # every existing DB and is depended on by other constraints.
