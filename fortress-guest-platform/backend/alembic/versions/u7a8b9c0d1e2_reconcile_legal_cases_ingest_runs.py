"""Reconcile legal.cases and legal.ingest_runs for Wave 7 ingest.

Revision ID: u7a8b9c0d1e2
Revises: 824b70503495
Create Date: 2026-05-02

PART A schema reconciliation for Constitution section 11.1. This migration is
intentionally idempotent because production-like databases already carry parts
of this schema from raw SQL/manual operational repairs, while shadow/test
databases may only have the older legal.cases surface.
"""
from __future__ import annotations

from alembic import op


revision = "u7a8b9c0d1e2"
down_revision = "824b70503495"
branch_labels = None
depends_on = None


_CASE_I_LAYOUT = """
{
  "primary_root": "/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i",
  "include_subdirs": ["curated", "case-i-context"],
  "exclude_subdirs": []
}
"""

_CASE_II_LAYOUT = """
{
  "primary_root": "/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii",
  "include_subdirs": ["curated"],
  "exclude_subdirs": []
}
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS legal")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.cases (
            case_slug TEXT PRIMARY KEY,
            docket TEXT,
            case_number TEXT,
            case_name TEXT,
            court TEXT,
            judge TEXT,
            case_type TEXT DEFAULT 'civil',
            our_role TEXT,
            status TEXT DEFAULT 'active',
            case_phase TEXT,
            opposing_counsel TEXT,
            privileged_counsel_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
            related_matters JSONB NOT NULL DEFAULT '[]'::jsonb,
            nas_layout JSONB NOT NULL DEFAULT '{}'::jsonb,
            extracted_entities JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS docket TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS case_number TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS case_name TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS court TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS judge TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS case_type TEXT DEFAULT 'civil'")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS our_role TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS case_phase TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS opposing_counsel TEXT")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS privileged_counsel_domains JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS related_matters JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS nas_layout JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS extracted_entities JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
    op.execute("ALTER TABLE legal.cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'legal.cases'::regclass
                  AND contype IN ('p', 'u')
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
        UPDATE legal.cases
           SET docket = COALESCE(docket, case_number),
               case_number = COALESCE(case_number, docket),
               privileged_counsel_domains = COALESCE(privileged_counsel_domains, '[]'::jsonb),
               related_matters = COALESCE(related_matters, '[]'::jsonb),
               nas_layout = COALESCE(nas_layout, '{}'::jsonb),
               updated_at = COALESCE(updated_at, NOW())
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.case_slug_aliases (
            old_slug TEXT PRIMARY KEY,
            new_slug TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_case_slug_aliases_new_slug
                FOREIGN KEY (new_slug) REFERENCES legal.cases (case_slug)
                DEFERRABLE INITIALLY IMMEDIATE
        )
    """)

    op.execute("""
        DO $$
        DECLARE
            fk_name TEXT;
        BEGIN
            SELECT conname INTO fk_name
              FROM pg_constraint
             WHERE conrelid = 'legal.case_slug_aliases'::regclass
               AND contype = 'f'
               AND condeferrable = FALSE
             LIMIT 1;

            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE legal.case_slug_aliases DROP CONSTRAINT %I', fk_name);
                ALTER TABLE legal.case_slug_aliases
                ADD CONSTRAINT fk_case_slug_aliases_new_slug
                FOREIGN KEY (new_slug) REFERENCES legal.cases (case_slug)
                DEFERRABLE INITIALLY IMMEDIATE;
            END IF;
        END $$;
    """)

    op.execute("""
        INSERT INTO legal.cases (
            case_slug, docket, case_number, case_name, court, judge,
            case_type, our_role, status, case_phase, related_matters,
            privileged_counsel_domains, nas_layout
        ) VALUES
            (
                '7il-v-knight-ndga-i',
                '2:21-CV-00226-RWS',
                '2:21-CV-00226-RWS',
                '7IL Properties LLC v. Knight (Case I)',
                'U.S. District Court, Northern District of Georgia',
                'Richard W. Story',
                'civil',
                'defendant',
                'closed_judgment_against',
                'closed',
                '["7il-v-knight-ndga-ii"]'::jsonb,
                '[]'::jsonb,
                ($$""" + _CASE_I_LAYOUT + """$$)::jsonb
            ),
            (
                '7il-v-knight-ndga-ii',
                '2:26-CV-00113-RWS',
                '2:26-CV-00113-RWS',
                '7IL Properties LLC v. Knight + Thor James (Case II)',
                'U.S. District Court, Northern District of Georgia',
                'Richard W. Story',
                'civil',
                'defendant_pro_se',
                'active',
                'counsel_search',
                '["7il-v-knight-ndga-i"]'::jsonb,
                '[]'::jsonb,
                ($$""" + _CASE_II_LAYOUT + """$$)::jsonb
            ),
            (
                'vanderburge-v-knight-fannin',
                'TBD',
                'TBD',
                'Karen Vanderburge v. Gary Knight + Lissa Knight',
                'Superior Court of Fannin County, Georgia',
                NULL,
                'civil',
                'defendant',
                'closed_settled',
                'closed_settled',
                '["7il-v-knight-ndga-i", "7il-v-knight-ndga-ii"]'::jsonb,
                '[]'::jsonb,
                '{}'::jsonb
            ),
            (
                'fish-trap-suv2026000013',
                'SUV2026000013',
                'SUV2026000013',
                'Generali Global Assistance, Inc. v. Cabin Rentals of Georgia, LLC',
                'Superior Court of Fannin County, State of Georgia (Appalachian Judicial Circuit)',
                NULL,
                'civil',
                'defendant',
                'active',
                NULL,
                '[]'::jsonb,
                '[]'::jsonb,
                '{}'::jsonb
            ),
            (
                'prime-trust-23-11161',
                '23-11161-JKS',
                '23-11161-JKS',
                'Prime Core Technologies, Inc. d/b/a Prime Trust',
                'U.S. Bankruptcy Court, District of Delaware',
                NULL,
                'bankruptcy',
                'creditor',
                'active',
                NULL,
                '[]'::jsonb,
                '[]'::jsonb,
                '{}'::jsonb
            )
        ON CONFLICT (case_slug) DO UPDATE SET
            docket = COALESCE(legal.cases.docket, EXCLUDED.docket, legal.cases.case_number),
            case_number = COALESCE(legal.cases.case_number, EXCLUDED.case_number, legal.cases.docket),
            case_name = COALESCE(legal.cases.case_name, EXCLUDED.case_name),
            court = COALESCE(legal.cases.court, EXCLUDED.court),
            judge = COALESCE(legal.cases.judge, EXCLUDED.judge),
            case_type = COALESCE(legal.cases.case_type, EXCLUDED.case_type),
            our_role = COALESCE(legal.cases.our_role, EXCLUDED.our_role),
            status = COALESCE(legal.cases.status, EXCLUDED.status),
            case_phase = COALESCE(legal.cases.case_phase, EXCLUDED.case_phase),
            related_matters = CASE
                WHEN EXCLUDED.case_slug IN ('7il-v-knight-ndga-i', '7il-v-knight-ndga-ii')
                    THEN EXCLUDED.related_matters
                ELSE COALESCE(legal.cases.related_matters, EXCLUDED.related_matters)
            END,
            privileged_counsel_domains = COALESCE(
                legal.cases.privileged_counsel_domains,
                EXCLUDED.privileged_counsel_domains
            ),
            nas_layout = CASE
                WHEN EXCLUDED.case_slug IN ('7il-v-knight-ndga-i', '7il-v-knight-ndga-ii')
                    THEN EXCLUDED.nas_layout
                ELSE COALESCE(legal.cases.nas_layout, EXCLUDED.nas_layout)
            END,
            updated_at = NOW()
    """)

    op.execute("""
        INSERT INTO legal.case_slug_aliases (old_slug, new_slug)
        VALUES ('7il-v-knight-ndga', '7il-v-knight-ndga-i')
        ON CONFLICT (old_slug) DO UPDATE SET new_slug = EXCLUDED.new_slug
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.ingest_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID UNIQUE DEFAULT gen_random_uuid(),
            case_slug TEXT NOT NULL,
            script_name TEXT NOT NULL,
            invocation_args JSONB NOT NULL DEFAULT '{}'::jsonb,
            args JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'complete', 'completed', 'error', 'failed', 'interrupted')),
            files_processed INTEGER NOT NULL DEFAULT 0,
            files_succeeded INTEGER NOT NULL DEFAULT 0,
            files_failed INTEGER NOT NULL DEFAULT 0,
            total_files INTEGER,
            processed INTEGER NOT NULL DEFAULT 0,
            errored INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            manifest_path TEXT,
            host TEXT,
            pid INTEGER,
            runtime_seconds NUMERIC(12, 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_ingest_runs_case_slug
                FOREIGN KEY (case_slug) REFERENCES legal.cases (case_slug)
                ON DELETE CASCADE
        )
    """)

    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS run_id UUID")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS invocation_args JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS args JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS files_processed INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS files_succeeded INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS files_failed INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS total_files INTEGER")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS processed INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS errored INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS skipped INTEGER DEFAULT 0")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS error_summary TEXT")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS manifest_path TEXT")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS host TEXT")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS pid INTEGER")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS runtime_seconds NUMERIC(12, 3)")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
    op.execute("ALTER TABLE legal.ingest_runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")

    op.execute("UPDATE legal.ingest_runs SET run_id = COALESCE(run_id, id)")
    op.execute("UPDATE legal.ingest_runs SET invocation_args = COALESCE(invocation_args, args, '{}'::jsonb)")
    op.execute("UPDATE legal.ingest_runs SET args = COALESCE(args, invocation_args, '{}'::jsonb)")
    op.execute("UPDATE legal.ingest_runs SET completed_at = COALESCE(completed_at, ended_at)")
    op.execute("UPDATE legal.ingest_runs SET ended_at = COALESCE(ended_at, completed_at)")
    op.execute("UPDATE legal.ingest_runs SET files_processed = COALESCE(files_processed, processed, 0)")
    op.execute("""
        UPDATE legal.ingest_runs
           SET files_succeeded = COALESCE(
                   files_succeeded,
                   GREATEST(COALESCE(processed, 0) - COALESCE(errored, 0), 0),
                   0
               ),
               files_failed = COALESCE(files_failed, errored, 0)
    """)
    op.execute("ALTER TABLE legal.ingest_runs ALTER COLUMN run_id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE legal.ingest_runs ALTER COLUMN invocation_args SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE legal.ingest_runs ALTER COLUMN args SET DEFAULT '{}'::jsonb")

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'legal.ingest_runs'::regclass
                  AND conname = 'uq_ingest_runs_run_id'
            ) THEN
                ALTER TABLE legal.ingest_runs
                ADD CONSTRAINT uq_ingest_runs_run_id UNIQUE (run_id);
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'legal.ingest_runs'::regclass
                  AND conname = 'fk_ingest_runs_case_slug'
            ) THEN
                ALTER TABLE legal.ingest_runs
                ADD CONSTRAINT fk_ingest_runs_case_slug
                FOREIGN KEY (case_slug) REFERENCES legal.cases (case_slug)
                ON DELETE CASCADE;
            END IF;
        END $$;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_runs_case_slug ON legal.ingest_runs (case_slug)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_runs_status ON legal.ingest_runs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_runs_started_at ON legal.ingest_runs (started_at DESC)")

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'legal.vault_documents'::regclass
                  AND conname = 'fk_vault_documents_case_slug'
                  AND condeferrable = FALSE
            ) THEN
                ALTER TABLE legal.vault_documents
                DROP CONSTRAINT fk_vault_documents_case_slug;
                ALTER TABLE legal.vault_documents
                ADD CONSTRAINT fk_vault_documents_case_slug
                FOREIGN KEY (case_slug) REFERENCES legal.cases (case_slug)
                ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS legal.ingest_runs")
    op.execute("DROP TABLE IF EXISTS legal.case_slug_aliases")
    op.execute("ALTER TABLE legal.cases DROP COLUMN IF EXISTS docket")
    op.execute("ALTER TABLE legal.cases DROP COLUMN IF EXISTS run_id")
