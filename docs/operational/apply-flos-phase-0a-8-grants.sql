-- ============================================================================
-- FLOS Phase 0a-8 — fortress_api role grants for legal mail intake
-- ============================================================================
-- Source: fortress-guest-platform/backend/alembic/versions/
--             t6e7f8g9h0a1_flos_phase_0a_8_role_grants.py
-- Companion to: INC-2026-04-28-flos-silent-intake (Bugs #4 + #5 durable fix)
--
-- Why this file exists:
--   The alembic chain is divergent (Issue #204), so we apply grant-only
--   migrations as raw SQL rather than running `alembic upgrade head`. This
--   file is a copy of the SQL inside the migration's upgrade() block so the
--   operator can psql-apply it against both databases without touching
--   alembic.
--
-- How to apply (operator runs from spark-2 or any host with psql access):
--
--   psql -U postgres -d fortress_db   -f docs/operational/apply-flos-phase-0a-8-grants.sql
--   psql -U postgres -d fortress_prod -f docs/operational/apply-flos-phase-0a-8-grants.sql
--
-- Idempotent: PostgreSQL GRANT statements are no-ops when the grant is
-- already in place. Safe to re-run.
--
-- Bilateral mirror discipline (ADR-001): apply to BOTH fortress_db AND
-- fortress_prod. Skipping either DB will reintroduce silent mirror drift.
--
-- Why UPDATE on sequences (Bug #5 correction): PostgreSQL setval() — which
-- the bilateral mirror writer calls to align fortress_prod's sequence with
-- the source row's id — requires UPDATE privilege on the sequence object.
-- USAGE alone (which governs nextval()/currval()) is insufficient. The
-- runtime patch initially granted only USAGE+SELECT and the mirror failed
-- on every cycle until UPDATE was added.
-- ============================================================================

BEGIN;

-- ── public.email_archive (existing legacy table; SELECT was already present)
GRANT INSERT, UPDATE, DELETE ON public.email_archive TO fortress_api;

-- ── public.email_archive_id_seq (RETURNING id + bilateral setval())
GRANT USAGE, SELECT, UPDATE ON SEQUENCE public.email_archive_id_seq TO fortress_api;

-- ── All current sequences in schema legal
--    Covers legal.event_log_id_seq, legal.mail_ingester_metrics_id_seq,
--    and any other sequences in schema legal at this snapshot.
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA legal TO fortress_api;

-- ── Default privileges so future legal.* sequences auto-grant on creation
ALTER DEFAULT PRIVILEGES IN SCHEMA legal
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO fortress_api;

-- ── Default privileges so future legal.* tables auto-grant on creation
ALTER DEFAULT PRIVILEGES IN SCHEMA legal
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fortress_api;

COMMIT;

-- ============================================================================
-- Verification queries (run after the script, on each DB)
-- ============================================================================
-- Expect 't' (true) for each row. If any returns 'f', the apply did not take.
--
--   SELECT has_table_privilege('fortress_api', 'public.email_archive', 'INSERT')   AS email_archive_insert,
--          has_table_privilege('fortress_api', 'public.email_archive', 'UPDATE')   AS email_archive_update,
--          has_table_privilege('fortress_api', 'public.email_archive', 'DELETE')   AS email_archive_delete;
--
--   SELECT has_sequence_privilege('fortress_api', 'public.email_archive_id_seq', 'USAGE')  AS ea_seq_usage,
--          has_sequence_privilege('fortress_api', 'public.email_archive_id_seq', 'SELECT') AS ea_seq_select,
--          has_sequence_privilege('fortress_api', 'public.email_archive_id_seq', 'UPDATE') AS ea_seq_update;
--
--   SELECT has_sequence_privilege('fortress_api', 'legal.event_log_id_seq', 'USAGE')  AS el_seq_usage,
--          has_sequence_privilege('fortress_api', 'legal.event_log_id_seq', 'SELECT') AS el_seq_select,
--          has_sequence_privilege('fortress_api', 'legal.event_log_id_seq', 'UPDATE') AS el_seq_update;
-- ============================================================================
