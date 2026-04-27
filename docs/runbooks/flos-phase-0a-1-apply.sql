-- FLOS Phase 0a-1 — legal mail ingester schema + seed + email_archive attribution.
-- Revision: q2b3c4d5e6f7  / Down revision: o0a1b2c3d4e5
-- Apply to: fortress_db, fortress_prod, fortress_shadow_test (skip fortress_shadow per #204)

BEGIN;

-- ── 1. legal.priority_sender_rules + seed ─────────────────────────
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
);

CREATE INDEX IF NOT EXISTS idx_priority_sender_rules_active
    ON legal.priority_sender_rules (is_active, priority)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_priority_sender_rules_case_slug
    ON legal.priority_sender_rules (case_slug)
    WHERE case_slug IS NOT NULL;

-- Seed rows — cross-case (court systems)
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
    ('%@peachcourt.com',         'P1', NULL, 'Georgia court e-filing system; any inbound is procedural'),
    ('%@fanninclerk%',           'P1', NULL, 'Fannin County clerk; orders + scheduling'),
    ('%@fanninsuperior%',        'P1', NULL, 'Fannin Superior Court chambers / clerks')
ON CONFLICT DO NOTHING;

-- Seed rows — fish-trap-suv2026000013 (Generali v CROG)
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
    ('%@stuartattorneys.com',    'P1', 'fish-trap-suv2026000013', 'Plaintiff counsel (J. David Stuart)'),
    ('%@rtsfg.com',              'P1', 'fish-trap-suv2026000013', 'Plaintiff collections (RTS Financial / Aaron Reaney)'),
    ('%@judgesosebee.com',       'P2', 'fish-trap-suv2026000013', 'Recused judge — historical; surface but lower priority')
ON CONFLICT DO NOTHING;

-- Seed rows — prime-trust-23-11161
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
    ('%@wbd-us.com',             'P1', 'prime-trust-23-11161', 'Plan Administrator (Weil, Bankruptcy & Desai)'),
    ('%detweiler%',              'P1', 'prime-trust-23-11161', 'Don Detweiler — Plan Administrator')
ON CONFLICT DO NOTHING;

-- ── 2. legal.mail_ingester_pause ──────────────────────────────────
CREATE TABLE IF NOT EXISTS legal.mail_ingester_pause (
    mailbox_alias TEXT PRIMARY KEY,
    paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_by TEXT NOT NULL,
    reason TEXT
);

-- ── 3. legal.mail_ingester_state ──────────────────────────────────
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
);

-- ── 4. legal.mail_ingester_metrics (Prometheus fallback) ──────────
CREATE TABLE IF NOT EXISTS legal.mail_ingester_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    mailbox_alias TEXT,
    label_key TEXT,
    label_value TEXT,
    counter_value BIGINT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_ingester_metrics_name_recorded
    ON legal.mail_ingester_metrics (metric_name, recorded_at DESC);

-- ── 5. legal.event_log (append-only audit) ────────────────────────
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
);

CREATE INDEX IF NOT EXISTS idx_event_log_unprocessed
    ON legal.event_log (emitted_at)
    WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_event_log_case_slug
    ON legal.event_log (case_slug, emitted_at DESC)
    WHERE case_slug IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_event_log_event_type
    ON legal.event_log (event_type, emitted_at DESC);

-- ── 6. email_archive — backfill ingested_from (only if table exists) ──
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name='email_archive') THEN
        UPDATE email_archive
           SET ingested_from = 'legacy_imap_producer:unknown'
         WHERE ingested_from IS NULL
           AND file_path LIKE 'imap://%';

        UPDATE email_archive
           SET ingested_from = 'historical:unknown'
         WHERE ingested_from IS NULL;

        ALTER TABLE email_archive
            ALTER COLUMN ingested_from SET NOT NULL;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'chk_email_archive_ingested_from_format') THEN
            ALTER TABLE email_archive
                ADD CONSTRAINT chk_email_archive_ingested_from_format
                CHECK (ingested_from ~ '^[a-z_]+:[a-z0-9_.-]+$');
        END IF;
    END IF;
END $$;

COMMIT;
