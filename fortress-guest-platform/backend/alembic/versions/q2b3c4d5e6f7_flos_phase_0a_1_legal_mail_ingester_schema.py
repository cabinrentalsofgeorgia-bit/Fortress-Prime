"""flos phase 0a-1 — legal mail ingester schema + seed + email_archive attribution.

Revision ID: q2b3c4d5e6f7
Revises: o0a1b2c3d4e5
Create Date: 2026-04-27

Phase 0a-1 of the FLOS legal email ingester rollout. See:
  docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md

Adds the schema substrate the new `legal_mail_ingester` (Phase 0a-2) writes to:

  legal.priority_sender_rules     — sender priority routing rules (+ 8 seed rows)
  legal.mail_ingester_pause       — operator-controlled per-mailbox pause
  legal.mail_ingester_state       — last_patrol_at + last_success_at per mailbox
  legal.mail_ingester_metrics     — counter store (Prometheus fallback)
  legal.event_log                 — append-only audit (FLOS Phase 1 dispatcher source)

Plus enforces source-attribution discipline on `email_archive`:

  - Backfill `ingested_from` for all existing rows (35,804 legacy producer rows
    + remaining historical rows)
  - SET NOT NULL on email_archive.ingested_from
  - CHECK constraint on format ^[a-z_]+:[a-z0-9_.-]+$

This NOT NULL is the architectural defense against future producer-mystery
incidents (per FLOS principle 10): every code path writing to email_archive
MUST declare its identity going forward.

Application targets: fortress_prod, fortress_db, fortress_shadow_test.
Skip: fortress_shadow (per Issue #204).

Bilateral mirror per ADR-001: identical schema on fortress_db + fortress_prod.
Migration does NOT bulk-copy split-brain historical rows between the two DBs
(per design §10 — that's a separate Phase 0a-1b sub-task if operator authorizes).
"""
from __future__ import annotations

from alembic import op


revision = "q2b3c4d5e6f7"
down_revision = "o0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. legal.priority_sender_rules + seed ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.priority_sender_rules (
            id BIGSERIAL PRIMARY KEY,
            sender_pattern TEXT NOT NULL,
            priority TEXT NOT NULL,
            case_slug TEXT,
            rationale TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_priority_sender_priority
                CHECK (priority IN ('P1', 'P2', 'P3'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_priority_sender_rules_active
            ON legal.priority_sender_rules (is_active, priority)
            WHERE is_active = TRUE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_priority_sender_rules_case_slug
            ON legal.priority_sender_rules (case_slug)
            WHERE case_slug IS NOT NULL
    """)

    # Seed rows — cross-case (court systems)
    op.execute("""
        INSERT INTO legal.priority_sender_rules
            (sender_pattern, priority, case_slug, rationale)
        VALUES
            ('%@peachcourt.com',         'P1', NULL,
             'Georgia court e-filing system; any inbound is procedural'),
            ('%@fanninclerk%',           'P1', NULL,
             'Fannin County clerk; orders + scheduling'),
            ('%@fanninsuperior%',        'P1', NULL,
             'Fannin Superior Court chambers / clerks')
        ON CONFLICT DO NOTHING
    """)

    # Seed rows — fish-trap-suv2026000013 (Generali v CROG)
    op.execute("""
        INSERT INTO legal.priority_sender_rules
            (sender_pattern, priority, case_slug, rationale)
        VALUES
            ('%@stuartattorneys.com',    'P1', 'fish-trap-suv2026000013',
             'Plaintiff counsel (J. David Stuart)'),
            ('%@rtsfg.com',              'P1', 'fish-trap-suv2026000013',
             'Plaintiff collections (RTS Financial / Aaron Reaney)'),
            ('%@judgesosebee.com',       'P2', 'fish-trap-suv2026000013',
             'Recused judge — historical; surface but lower priority')
        ON CONFLICT DO NOTHING
    """)

    # Seed rows — prime-trust-23-11161
    op.execute("""
        INSERT INTO legal.priority_sender_rules
            (sender_pattern, priority, case_slug, rationale)
        VALUES
            ('%@wbd-us.com',             'P1', 'prime-trust-23-11161',
             'Plan Administrator (Weil, Bankruptcy & Desai)'),
            ('%detweiler%',              'P1', 'prime-trust-23-11161',
             'Don Detweiler — Plan Administrator')
        ON CONFLICT DO NOTHING
    """)

    # ── 2. legal.mail_ingester_pause ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.mail_ingester_pause (
            mailbox_alias TEXT PRIMARY KEY,
            paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paused_by TEXT NOT NULL,
            reason TEXT
        )
    """)

    # ── 3. legal.mail_ingester_state ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.mail_ingester_state (
            mailbox_alias TEXT PRIMARY KEY,
            last_patrol_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            last_error_at TIMESTAMPTZ,
            last_error TEXT,
            messages_ingested_total BIGINT NOT NULL DEFAULT 0,
            messages_deduped_total BIGINT NOT NULL DEFAULT 0,
            messages_errored_total BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── 4. legal.mail_ingester_metrics (Prometheus fallback) ──────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.mail_ingester_metrics (
            id BIGSERIAL PRIMARY KEY,
            metric_name TEXT NOT NULL,
            mailbox_alias TEXT,
            label_key TEXT,
            label_value TEXT,
            counter_value BIGINT NOT NULL DEFAULT 0,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mail_ingester_metrics_name_recorded
            ON legal.mail_ingester_metrics (metric_name, recorded_at DESC)
    """)

    # ── 5. legal.event_log (append-only audit) ────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.event_log (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            case_slug TEXT,
            event_payload JSONB NOT NULL,
            emitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            emitted_by TEXT NOT NULL,
            processed_at TIMESTAMPTZ,
            processed_by TEXT,
            result JSONB,
            CONSTRAINT chk_event_log_emitted_by_format
                CHECK (emitted_by ~ '^[a-z_]+:[a-z0-9_.-]+$')
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_log_unprocessed
            ON legal.event_log (emitted_at)
            WHERE processed_at IS NULL
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_log_case_slug
            ON legal.event_log (case_slug, emitted_at DESC)
            WHERE case_slug IS NOT NULL
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_log_event_type
            ON legal.event_log (event_type, emitted_at DESC)
    """)

    # ── 6. email_archive — backfill ingested_from ─────────────────────
    # Pass 1: legacy producer rows (file_path LIKE 'imap://%')
    op.execute("""
        UPDATE email_archive
           SET ingested_from = 'legacy_imap_producer:unknown'
         WHERE ingested_from IS NULL
           AND file_path LIKE 'imap://%'
    """)

    # Pass 2: pre-legacy historical rows (Maildir scrape, GMAIL_ARCHIVE, etc.)
    op.execute("""
        UPDATE email_archive
           SET ingested_from = 'historical:unknown'
         WHERE ingested_from IS NULL
    """)

    # ── 7. email_archive — enforce NOT NULL + CHECK going forward ─────
    op.execute("""
        ALTER TABLE email_archive
            ALTER COLUMN ingested_from SET NOT NULL
    """)

    op.execute("""
        ALTER TABLE email_archive
            ADD CONSTRAINT chk_email_archive_ingested_from_format
            CHECK (ingested_from ~ '^[a-z_]+:[a-z0-9_.-]+$')
    """)


def downgrade() -> None:
    # Reverse order. Note: cannot truly un-backfill the ingested_from values;
    # downgrade leaves them populated (data preservation > schema purity).
    op.execute("""
        ALTER TABLE email_archive
            DROP CONSTRAINT IF EXISTS chk_email_archive_ingested_from_format
    """)

    op.execute("""
        ALTER TABLE email_archive
            ALTER COLUMN ingested_from DROP NOT NULL
    """)

    op.execute("DROP INDEX IF EXISTS legal.idx_event_log_event_type")
    op.execute("DROP INDEX IF EXISTS legal.idx_event_log_case_slug")
    op.execute("DROP INDEX IF EXISTS legal.idx_event_log_unprocessed")
    op.execute("DROP TABLE IF EXISTS legal.event_log")

    op.execute("DROP INDEX IF EXISTS legal.idx_mail_ingester_metrics_name_recorded")
    op.execute("DROP TABLE IF EXISTS legal.mail_ingester_metrics")

    op.execute("DROP TABLE IF EXISTS legal.mail_ingester_state")
    op.execute("DROP TABLE IF EXISTS legal.mail_ingester_pause")

    op.execute("DROP INDEX IF EXISTS legal.idx_priority_sender_rules_case_slug")
    op.execute("DROP INDEX IF EXISTS legal.idx_priority_sender_rules_active")
    op.execute("DROP TABLE IF EXISTS legal.priority_sender_rules")
